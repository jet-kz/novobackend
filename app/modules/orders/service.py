import hashlib
import hmac
import math
import re
import secrets
import uuid
from types import SimpleNamespace
from urllib.parse import quote
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core import config
from app.core.access import get_owned_store_ids, is_admin, is_rider
from app.core.serializers import model_to_dict, to_jsonable
from app.modules.deliveries.models import Delivery
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.orders.status import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    DELIVERED,
    FAILED,
    PENDING,
    PICKED_UP,
    READY_FOR_PICKUP,
    RIDER_ASSIGNED,
    TransitionError,
    assert_transition_allowed,
    canonical_stored_status,
    normalize_order_status,
)
from app.modules.products.models import Product
from app.modules.stores.models import Store
from app.modules.notifications import service as notify

DEFAULT_DELIVERY_COORDS = (6.5244, 3.3792)  # (lat, lon) Lagos — used only when the client sends none
MAX_TIP = 100_000.0
MAX_ITEM_QUANTITY = 99
ACTIVE_DELIVERY_STATUSES = ("assigned", "picked_up")


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested in tests/test_order_pricing.py)
# ─────────────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_guest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pickup_code_for(order_id: str) -> str:
    """Stable 4-digit code the merchant reads to the rider at pickup. Derived, so no column is needed."""
    salt = config.SUPABASE_JWT_SECRET or "novo-pickup"
    digest = hashlib.sha256(f"{salt}:{order_id}".encode()).hexdigest()
    return str(1000 + int(digest[:8], 16) % 9000)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _option_price_index(product) -> dict:
    """id -> price for every option a product defines, across all option formats."""
    index = {}
    for opt in (product.protein_options or []) + (product.extras_options or []):
        if isinstance(opt, dict) and opt.get("id") is not None:
            index[str(opt["id"])] = float(opt.get("price") or 0)
    for group in product.option_groups or []:
        if not isinstance(group, dict):
            continue
        for opt in group.get("options") or []:
            if isinstance(opt, dict) and opt.get("id") is not None:
                index[str(opt["id"])] = float(opt.get("price") or 0)
    for opt in getattr(product, "options", None) or []:
        index[str(opt.id)] = float(opt.price or 0)
    return index


def price_order_items(raw_items: list, products_by_id: dict, store_id) -> tuple[list[dict], float]:
    """
    Turn client cart lines into priced order items using catalogue prices only.
    Client-sent prices are ignored. Raises ValueError with a user-facing message.
    """
    if not raw_items:
        raise ValueError("Your order has no items")

    priced, subtotal = [], 0.0
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise ValueError("Invalid order item")
        nested = raw.get("product") if isinstance(raw.get("product"), dict) else {}
        pid_raw = raw.get("product_id") or raw.get("productId") or nested.get("id")
        try:
            pid = uuid.UUID(str(pid_raw))
        except (TypeError, ValueError):
            raise ValueError("Order contains an invalid product")

        product = products_by_id.get(pid)
        if not product:
            raise ValueError("An item in your cart is no longer available")
        if store_id is not None and product.store_id != store_id:
            raise ValueError("All items must come from the same store")
        if not product.in_stock:
            raise ValueError(f"{product.name} is out of stock")

        try:
            quantity = int(raw["quantity"]) if raw.get("quantity") is not None else 1
        except (TypeError, ValueError):
            raise ValueError("Invalid quantity")
        if quantity < 1 or quantity > MAX_ITEM_QUANTITY:
            raise ValueError(f"Quantity for {product.name} must be between 1 and {MAX_ITEM_QUANTITY}")

        option_prices = _option_price_index(product)
        addons_in = raw.get("addons") or raw.get("selectedOptions") or []
        addons_out, addon_total = [], 0.0
        for addon in addons_in if isinstance(addons_in, list) else []:
            aid = str(addon.get("id")) if isinstance(addon, dict) else None
            if aid is None or aid not in option_prices:
                raise ValueError(f"An option for {product.name} is no longer available")
            addon_total += option_prices[aid]
            addons_out.append({"id": aid, "name": addon.get("name"), "price": option_prices[aid]})

        unit_price = round(float(product.price or 0) + addon_total, 2)
        subtotal += unit_price * quantity
        priced.append({
            "product_id": pid,
            "name": product.name,
            "price": unit_price,
            "quantity": quantity,
            "addons": to_jsonable(addons_out) if addons_out else None,
        })
    return priced, round(subtotal, 2)


def _coord(value, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


# ─────────────────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────────────────

def serialize_order(
    order: Order,
    store: Optional[Store] = None,
    delivery: Optional[Delivery] = None,
    include_pickup_code: bool = False,
) -> dict:
    data = model_to_dict(order)
    data.pop("guest_token_hash", None)
    data["is_guest"] = str(order.customer_id or "").startswith("guest:")
    data["status"] = canonical_stored_status(order.status)
    data["items"] = [model_to_dict(item) for item in (order.__dict__.get("items") or [])]
    data["store_id"] = str(order.store_id) if order.store_id else None
    if store is not None:
        data["store_name"] = store.name
        data["store_address"] = store.address
        data["store_phone"] = store.phone
    if delivery is not None and delivery.rider_id:
        data["rider_id"] = delivery.rider_id
        data["delivery_id"] = str(delivery.id)
        data["delivery_status"] = delivery.status
        data["rider_earnings"] = delivery.rider_earnings
    if include_pickup_code:
        data["pickup_code"] = pickup_code_for(order.id)
    return data


class OrderService:
    # ── Reads ────────────────────────────────────────────────────────────────

    @staticmethod
    async def _decorate(db: AsyncSession, orders: list, include_pickup_code: bool = False) -> list[dict]:
        if not orders:
            return []
        store_ids = {o.store_id for o in orders if o.store_id}
        stores = {}
        if store_ids:
            res = await db.execute(select(Store).where(Store.id.in_(store_ids)))
            stores = {s.id: s for s in res.scalars().all()}
        res = await db.execute(
            select(Delivery).where(Delivery.order_id.in_([o.id for o in orders]), Delivery.rider_id.is_not(None))
        )
        deliveries = {}
        for d in res.scalars().all():
            deliveries[d.order_id] = d
        return [
            serialize_order(o, stores.get(o.store_id), deliveries.get(o.id), include_pickup_code)
            for o in orders
        ]

    @staticmethod
    async def get_all_orders(
        db: AsyncSession,
        current_user: dict,
        store_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        order_status: Optional[str] = None,
    ):
        """
        Scope by role:
          admin    -> everything (optionally filtered)
          merchant -> orders for stores they own
          rider    -> jobs ready for pickup with no rider, plus jobs assigned to them
          customer -> their own orders
        """
        stmt = select(Order).options(selectinload(Order.items))
        user_id = current_user["user_id"]
        include_code = False

        if is_admin(current_user):
            include_code = True
            if store_id:
                try:
                    stmt = stmt.where(Order.store_id == uuid.UUID(store_id))
                except ValueError:
                    return []
            if customer_id:
                stmt = stmt.where(Order.customer_id == customer_id)
        else:
            owned = await get_owned_store_ids(db, user_id)
            if owned:
                include_code = True
                if store_id:
                    try:
                        target = uuid.UUID(store_id)
                    except ValueError:
                        return []
                    if target not in owned:
                        return []
                    stmt = stmt.where(Order.store_id == target)
                else:
                    stmt = stmt.where(Order.store_id.in_(owned))
                # Card orders reach the kitchen only once Paystack confirms payment.
                stmt = stmt.where((Order.payment_method != "card") | (Order.payment_status == "paid"))
            elif is_rider(current_user):
                assigned = select(Delivery.order_id).where(Delivery.rider_id == user_id)
                taken = select(Delivery.order_id).where(
                    Delivery.rider_id.is_not(None), Delivery.status.in_(ACTIVE_DELIVERY_STATUSES)
                )
                stmt = stmt.where(
                    (Order.id.in_(assigned))
                    | ((Order.status == READY_FOR_PICKUP) & (Order.id.not_in(taken)))
                    | (Order.customer_id == user_id)
                )
            else:
                stmt = stmt.where(Order.customer_id == user_id)

        if order_status:
            try:
                stmt = stmt.where(Order.status == normalize_order_status(order_status))
            except ValueError:
                pass

        result = await db.execute(stmt.order_by(Order.created_at.desc()))
        return await OrderService._decorate(db, list(result.scalars().unique().all()), include_code)

    @staticmethod
    async def _load(db: AsyncSession, order_id: str) -> Order:
        result = await db.execute(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    @staticmethod
    async def _active_delivery(db: AsyncSession, order_id: str) -> Optional[Delivery]:
        res = await db.execute(
            select(Delivery).where(Delivery.order_id == order_id).order_by(Delivery.created_at.desc())
        )
        return res.scalars().first()

    @staticmethod
    async def _viewer_role(db: AsyncSession, order: Order, current_user: dict) -> Optional[str]:
        """Return admin / merchant / rider / customer for this order, or None when unrelated."""
        if is_admin(current_user):
            return "admin"
        uid = current_user["user_id"]
        if order.store_id and order.store_id in await get_owned_store_ids(db, uid):
            return "merchant"
        if is_rider(current_user):
            delivery = await OrderService._active_delivery(db, order.id)
            if delivery and delivery.rider_id == uid:
                return "rider"
            if canonical_stored_status(order.status) == READY_FOR_PICKUP and not (delivery and delivery.rider_id):
                return "rider"
        if order.customer_id == uid:
            return "customer"
        return None

    @staticmethod
    async def get_by_id(db: AsyncSession, order_id: str, current_user: dict):
        order = await OrderService._load(db, order_id)
        role = await OrderService._viewer_role(db, order, current_user)
        if role is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this order")
        decorated = await OrderService._decorate(db, [order], include_pickup_code=role in ("admin", "merchant"))
        return decorated[0]

    @staticmethod
    async def get_status_history(db: AsyncSession, order_id: str, current_user: dict):
        order = await OrderService._load(db, order_id)
        if await OrderService._viewer_role(db, order, current_user) is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this order")
        result = await db.execute(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at.asc())
        )
        return [model_to_dict(row) for row in result.scalars().all()]

    # ── Create ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _price_checkout(db: AsyncSession, current_user: dict, data: dict, require_address: bool = True):
        """Single pricing path shared by /orders/quote and order creation."""
        from app.modules.pricing.schemas import PricingCalculateRequest
        from app.modules.pricing.service import PricingEngine

        payload = dict(data or {})
        customer_id = current_user["user_id"]

        store_raw = payload.get("store_id") or payload.get("storeId")
        try:
            store_uuid = uuid.UUID(str(store_raw))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A valid store_id is required")
        store_res = await db.execute(select(Store).where(Store.id == store_uuid, Store.is_deleted == False))
        store = store_res.scalar_one_or_none()
        if not store:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found")
        if not store.is_open:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{store.name} is currently closed")

        raw_items = payload.get("items") or []
        ids = set()
        for raw in raw_items:
            if isinstance(raw, dict):
                nested = raw.get("product") if isinstance(raw.get("product"), dict) else {}
                try:
                    ids.add(uuid.UUID(str(raw.get("product_id") or raw.get("productId") or nested.get("id"))))
                except (TypeError, ValueError):
                    pass
        products_by_id = {}
        if ids:
            res = await db.execute(
                select(Product)
                .options(selectinload(Product.options))
                .where(Product.id.in_(ids), Product.is_deleted == False)
            )
            products_by_id = {p.id: p for p in res.scalars().all()}

        try:
            items, subtotal = price_order_items(raw_items, products_by_id, store.id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

        if subtotal <= 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order total must be greater than zero")

        min_order = float(((store.settings or {}) if isinstance(store.settings, dict) else {}).get("min_order") or 0)
        if min_order and subtotal < min_order:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum order for {store.name} is ₦{min_order:,.0f}",
            )

        address = str(payload.get("delivery_address") or "").strip()
        if require_address and len(address) < 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter a delivery address")

        try:
            tip = round(float(payload.get("tip") or 0), 2)
        except (TypeError, ValueError):
            tip = 0.0
        if tip < 0 or tip > MAX_TIP:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tip amount")

        payment_method = str(payload.get("payment_method") or "card").lower()
        if payment_method not in ("card", "cash", "transfer"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported payment method")

        lat = _coord(payload.get("delivery_latitude"), DEFAULT_DELIVERY_COORDS[0], -90, 90)
        lon = _coord(payload.get("delivery_longitude"), DEFAULT_DELIVERY_COORDS[1], -180, 180)
        distance_km = 3.0
        loc = store.location if isinstance(store.location, dict) else None
        if loc and loc.get("latitude") is not None and payload.get("delivery_latitude") is not None:
            distance_km = round(min(haversine_km(loc["latitude"], loc["longitude"], lat, lon), 50.0), 2)

        promo_code = payload.get("promo_code") or payload.get("promoCode")
        breakdown = await PricingEngine.calculate_checkout_pricing(
            db,
            PricingCalculateRequest(
                subtotal=subtotal,
                merchant_id=str(store.merchant_id),
                user_id=customer_id,
                promo_code=promo_code,
                distance_km=distance_km,
            ),
        )
        if promo_code and not breakdown.applied_promo_code and require_address:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Promo code is not valid for this order")

        return SimpleNamespace(
            store=store, items=items, breakdown=breakdown, tip=tip, address=address,
            payment_method=payment_method, lat=lat, lon=lon, distance_km=distance_km, promo_code=promo_code,
        )

    @staticmethod
    async def quote(db: AsyncSession, current_user: dict, data: dict) -> dict:
        """Exactly what create_order would charge, without saving anything."""
        ctx = await OrderService._price_checkout(db, current_user, data, require_address=False)
        b = ctx.breakdown
        return {
            "subtotal": b.subtotal,
            "delivery_fee": b.delivery_fee,
            "service_fee": b.service_fee,
            "discount": b.discount,
            "tip": ctx.tip,
            "total": round(b.total + ctx.tip, 2),
            "distance_km": ctx.distance_km,
            "applied_promo_code": b.applied_promo_code,
            "promo_valid": bool(b.applied_promo_code) if ctx.promo_code else None,
            "items": [{**to_jsonable(i), "product_id": str(i["product_id"])} for i in ctx.items],
        }

    @staticmethod
    async def create_order(db: AsyncSession, current_user: dict, data: dict, guest_token: Optional[str] = None):
        """
        Server-authoritative checkout: item prices, subtotal, fees, discount and total are all
        computed here. Client-sent amounts are ignored. Order, items, pricing snapshot, promo
        redemption and the first status row commit in one transaction.
        """
        from app.modules.pricing.models import PromotionRedemption
        from app.modules.pricing.service import PricingEngine

        payload = dict(data or {})
        customer_id = current_user["user_id"]
        ctx = await OrderService._price_checkout(db, current_user, payload)
        store, items, breakdown, tip = ctx.store, ctx.items, ctx.breakdown, ctx.tip
        address, payment_method, lat, lon = ctx.address, ctx.payment_method, ctx.lat, ctx.lon

        order = Order(
            id=f"ORD-{uuid.uuid4().hex[:10].upper()}",
            customer_id=customer_id,
            customer_name=str(payload.get("customer_name") or "").strip()[:120] or (current_user.get("email") or "Customer"),
            customer_phone=str(payload.get("customer_phone") or "").strip()[:50] or None,
            customer_email=(current_user.get("email") or str(payload.get("customer_email") or "").strip() or None),
            guest_token_hash=hash_guest_token(guest_token) if guest_token else None,
            store_id=store.id,
            subtotal=breakdown.subtotal,
            delivery_fee=breakdown.delivery_fee,
            service_fee=breakdown.service_fee,
            tip=tip,
            total=round(breakdown.total + tip, 2),
            payment_status="unpaid",
            payment_method=payment_method,
            status=PENDING,
            currency="NGN",
            delivery_latitude=lat,
            delivery_longitude=lon,
            delivery_address=address[:255],
        )
        db.add(order)
        await db.flush()
        for item in items:
            db.add(OrderItem(order_id=order.id, **item))

        await PricingEngine.create_pricing_snapshot(db, order.id, breakdown)

        if breakdown.applied_promo_code:
            from app.modules.pricing.models import PromotionCampaign

            camp_res = await db.execute(
                select(PromotionCampaign).where(PromotionCampaign.code == breakdown.applied_promo_code)
            )
            campaign = camp_res.scalar_one_or_none()
            if campaign:
                campaign.current_redemptions = (campaign.current_redemptions or 0) + 1
                db.add(PromotionRedemption(
                    campaign_id=campaign.id,
                    user_id=customer_id,
                    order_id=order.id,
                    discount_applied=breakdown.discount,
                ))

        db.add(OrderStatusHistory(order_id=order.id, old_status=None, new_status=PENDING, changed_by_id=customer_id))
        await db.commit()
        track_url = None
        if guest_token:
            track_url = f"{config.FRONTEND_URL}/track/{quote(order.id)}?t={quote(guest_token)}"
        notify.order_placed(order.id, track_url)

        order = await OrderService._load(db, order.id)
        return serialize_order(order, store)

    # ── Guest checkout ───────────────────────────────────────────────────────

    @staticmethod
    def guest_user(email: Optional[str] = None) -> dict:
        """Stand-in identity for a guest. Guests never hit role-protected routes."""
        return {"user_id": f"guest:{uuid.uuid4()}", "email": email, "roles": ["guest"], "raw_payload": {}}

    @staticmethod
    def _validate_guest_contact(data: dict) -> tuple[str, str, Optional[str]]:
        name = str(data.get("customer_name") or "").strip()
        phone = str(data.get("customer_phone") or "").strip()
        email = str(data.get("customer_email") or "").strip().lower() or None
        if len(name) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter your name")
        if len(re.sub(r"\D", "", phone)) < 10:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please enter a phone number the rider can call")
        if email and not EMAIL_RE.match(email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That email address doesn't look right")
        return name, phone, email

    @staticmethod
    async def quote_guest(db: AsyncSession, data: dict) -> dict:
        payload = {k: v for k, v in (data or {}).items() if k not in ("promo_code", "promoCode")}
        return await OrderService.quote(db, OrderService.guest_user(), payload)

    @staticmethod
    async def create_guest_order(db: AsyncSession, data: dict) -> dict:
        """Checkout without an account. Returns the order plus a secret token for the tracking link."""
        name, phone, email = OrderService._validate_guest_contact(data or {})
        payload = {k: v for k, v in (data or {}).items() if k not in ("promo_code", "promoCode")}
        payload.update(customer_name=name, customer_phone=phone, customer_email=email)
        token = secrets.token_urlsafe(24)
        order = await OrderService.create_order(db, OrderService.guest_user(email), payload, guest_token=token)
        return {**order, "guest_token": token}

    @staticmethod
    async def load_guest_order(db: AsyncSession, order_id: str, token: str) -> Order:
        order = await db.get(Order, order_id) if order_id else None
        if not order or not order.guest_token_hash or not token or not hmac.compare_digest(
            order.guest_token_hash, hash_guest_token(token)
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    @staticmethod
    async def get_guest_order(db: AsyncSession, order_id: str, token: str) -> dict:
        order = await OrderService.load_guest_order(db, order_id, token)
        order = await OrderService._load(db, order.id)
        decorated = await OrderService._decorate(db, [order])
        history = await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at.asc())
        )
        return {**decorated[0], "history": [model_to_dict(h) for h in history.scalars().all()]}

    @staticmethod
    async def cancel_guest_order(db: AsyncSession, order_id: str, token: str, reason: Optional[str] = None) -> dict:
        order = await OrderService.load_guest_order(db, order_id, token)
        await OrderService.cancel_order(db, order.id, {"user_id": order.customer_id, "roles": ["guest"]}, reason)
        return await OrderService.get_guest_order(db, order_id, token)

    # ── Status changes ───────────────────────────────────────────────────────

    @staticmethod
    async def update_status(db: AsyncSession, order_id: str, new_status: str, current_user: dict, payload: Optional[dict] = None):
        payload = payload or {}
        try:
            target = normalize_order_status(new_status)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status is required")

        order = await OrderService._load(db, order_id)
        role = await OrderService._viewer_role(db, order, current_user)
        if role in (None, "customer"):
            if role == "customer" and target == CANCELLED:
                return await OrderService.cancel_order(db, order_id, current_user, payload.get("reason"))
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this order")

        current = canonical_stored_status(order.status)
        try:
            assert_transition_allowed(current, target, role)
        except TransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

        if role == "merchant" and target != CANCELLED and order.payment_method == "card" and order.payment_status != "paid":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This card order has not been paid yet")

        uid = current_user["user_id"]
        delivery = await OrderService._active_delivery(db, order.id)
        now = datetime.now(timezone.utc)

        if target == RIDER_ASSIGNED:
            if role != "rider":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only a rider can accept a delivery")
            if delivery and delivery.rider_id and delivery.status in ACTIVE_DELIVERY_STATUSES:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This job was already taken by another rider")
            delivery = await OrderService._assign_rider(db, order, uid, delivery, now)

        elif target == PICKED_UP:
            if not delivery or not delivery.rider_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No rider is assigned to this order")
            if role == "rider":
                if delivery.rider_id != uid:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This job is assigned to another rider")
                code = str(payload.get("pickup_code") or "").strip()
                if code != pickup_code_for(order.id):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect pickup code. Ask the store for the 4-digit code.")
            delivery.status = "picked_up"
            delivery.picked_up_at = now

        elif target in (DELIVERED, FAILED):
            if role == "rider" and (not delivery or delivery.rider_id != uid):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This job is assigned to another rider")
            if delivery:
                delivery.status = "delivered" if target == DELIVERED else "failed"
                if target == DELIVERED:
                    delivery.delivered_at = now
                    from app.modules.riders.models import RiderProfile

                    rider = await db.get(RiderProfile, delivery.rider_id) if delivery.rider_id else None
                    if rider:
                        rider.total_deliveries = (rider.total_deliveries or 0) + 1
                        rider.status = "online"
            if target == DELIVERED and order.payment_method in ("cash", "transfer") and order.payment_status != "paid":
                order.payment_status = "paid"  # collected by the rider at the door

        elif target == READY_FOR_PICKUP and current == RIDER_ASSIGNED:
            # rider released the job
            if delivery:
                delivery.rider_id = None
                delivery.status = "pending_assignment"
                delivery.assigned_at = None

        order.status = target
        db.add(OrderStatusHistory(
            order_id=order.id,
            old_status=current,
            new_status=target,
            changed_by_id=uid,
            cancellation_reason=(payload.get("reason") or None) if target == CANCELLED else None,
        ))
        await db.commit()
        notify.order_status_changed(order.id, target, payload.get("reason") or None)
        if target == RIDER_ASSIGNED and delivery:
            notify.rider_assigned(order.id, uid, delivery.rider_earnings)
        return await OrderService.get_by_id(db, order.id, current_user)

    @staticmethod
    async def _assign_rider(db: AsyncSession, order: Order, rider_id: str, delivery: Optional[Delivery], now):
        from app.modules.pricing.models import PricingSnapshot
        from app.modules.riders.service import RiderService

        rider = await RiderService.get_or_create_for_user(db, rider_id)
        if rider.approval_status != "approved":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your rider account hasn't been approved yet")
        if rider.status == "offline":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Go online before accepting jobs")

        snap_res = await db.execute(select(PricingSnapshot).where(PricingSnapshot.order_id == order.id))
        snapshot = snap_res.scalar_one_or_none()
        earnings = round(float(snapshot.rider_earning if snapshot else (order.delivery_fee or 0) * 0.85) + float(order.tip or 0), 2)

        if delivery is None:
            store = await db.get(Store, order.store_id) if order.store_id else None
            loc = store.location if store is not None and isinstance(store.location, dict) else None
            pickup = (
                f"SRID=4326;POINT({loc['longitude']} {loc['latitude']})" if loc
                else f"SRID=4326;POINT({DEFAULT_DELIVERY_COORDS[1]} {DEFAULT_DELIVERY_COORDS[0]})"
            )
            delivery = Delivery(
                order_id=order.id,
                pickup_location=pickup,
                dropoff_location=f"SRID=4326;POINT({order.delivery_longitude} {order.delivery_latitude})",
                currency=order.currency or "NGN",
            )
            db.add(delivery)
        delivery.rider_id = rider_id
        delivery.status = "assigned"
        delivery.assigned_at = now
        delivery.fee = float(order.delivery_fee or 0)
        delivery.rider_earnings = earnings
        rider.status = "busy"
        await db.flush()
        return delivery

    @staticmethod
    async def cancel_order(db: AsyncSession, order_id: str, current_user: dict, reason: Optional[str] = None):
        order = await OrderService._load(db, order_id)
        if order.customer_id != current_user["user_id"] and not is_admin(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to cancel this order")
        current = canonical_stored_status(order.status)
        if current not in CANCELLABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This order is already being prepared and can no longer be cancelled",
            )
        order.status = CANCELLED
        db.add(OrderStatusHistory(
            order_id=order.id,
            old_status=current,
            new_status=CANCELLED,
            changed_by_id=current_user["user_id"],
            cancellation_reason=reason,
        ))
        await db.commit()
        notify.order_status_changed(order.id, CANCELLED, reason, by_customer=order.customer_id == current_user["user_id"])
        return await OrderService.get_by_id(db, order.id, current_user)
