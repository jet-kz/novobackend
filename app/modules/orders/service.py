from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.orders.models import Order, OrderStatusHistory
from typing import Optional


CANCELLABLE_STATUSES = {"CART", "PENDING", "CONFIRMED"}
RESTRICTED_TRANSITIONS = {"DISPATCHED", "DELIVERED", "FAILED", "CANCELLED"}


import uuid
from app.modules.merchants.models import Merchant
from app.modules.stores.models import Store

class OrderService:
    @staticmethod
    async def get_all_orders(db: AsyncSession, current_user: dict, store_id: Optional[str] = None, customer_id: Optional[str] = None, order_status: Optional[str] = None):
        stmt = select(Order)
        is_admin = "admin" in current_user.get("roles", [])

        if not is_admin:
            merch_res = await db.execute(select(Merchant).where(Merchant.owner_id == current_user["user_id"], Merchant.is_deleted == False))
            merchant = merch_res.scalar_one_or_none()

            if merchant:
                stores_res = await db.execute(select(Store.id).where(Store.merchant_id == merchant.id, Store.is_deleted == False))
                store_ids = list(stores_res.scalars().all())

                if not store_ids:
                    return []

                if store_id:
                    try:
                        target_uuid = uuid.UUID(store_id)
                        if target_uuid in store_ids:
                            stmt = stmt.where(Order.store_id == target_uuid)
                        else:
                            return []
                    except Exception:
                        return []
                else:
                    stmt = stmt.where(Order.store_id.in_(store_ids))
            else:
                stmt = stmt.where(Order.customer_id == current_user["user_id"])
        else:
            if store_id:
                try:
                    stmt = stmt.where(Order.store_id == uuid.UUID(store_id))
                except Exception:
                    pass
            elif customer_id:
                stmt = stmt.where(Order.customer_id == customer_id)

        if order_status:
            stmt = stmt.where(Order.status == order_status.upper())

        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, order_id: str):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    @staticmethod
    async def create_order(db: AsyncSession, customer_id: str, data: dict):
        data["customer_id"] = customer_id
        data["status"] = "PENDING"
        if "id" not in data or not data["id"]:
            data["id"] = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        if "customer_name" not in data or not data["customer_name"]:
            data["customer_name"] = "Customer"
        if "currency" not in data or not data["currency"]:
            data["currency"] = "NGN"
        if "delivery_latitude" not in data:
            data["delivery_latitude"] = 6.5244
        if "delivery_longitude" not in data:
            data["delivery_longitude"] = 3.3792
        if "delivery_address" not in data or not data["delivery_address"]:
            data["delivery_address"] = "Standard Customer Address"

        if "store_id" in data and isinstance(data["store_id"], str):
            try:
                data["store_id"] = uuid.UUID(data["store_id"])
            except Exception:
                pass
        if "storeId" in data and "store_id" not in data:
            try:
                data["store_id"] = uuid.UUID(data.pop("storeId"))
            except Exception:
                pass

        items_data = data.pop("items", [])
        promo_code = data.pop("promo_code", None)

        order = Order(**data)
        db.add(order)
        await db.flush()

        # Compute & Freeze Immutable Pricing Snapshot
        from app.modules.pricing.service import PricingEngine
        from app.modules.pricing.schemas import PricingCalculateRequest

        m_id = str(order.store_id) if order.store_id else None
        calc_req = PricingCalculateRequest(
            subtotal=order.subtotal,
            merchant_id=m_id,
            user_id=customer_id,
            promo_code=promo_code,
            distance_km=3.0
        )
        breakdown = await PricingEngine.calculate_checkout_pricing(db, calc_req)
        await PricingEngine.create_pricing_snapshot(db, order.id, breakdown)

        # Sync calculated total & fees back to Order
        order.delivery_fee = breakdown.delivery_fee
        order.service_fee = breakdown.service_fee
        order.total = breakdown.total

        # log initial status event
        history = OrderStatusHistory(
            order_id=order.id, old_status=None, new_status="PENDING", changed_by_id=customer_id
        )
        db.add(history)
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def update_status(db: AsyncSession, order_id: str, new_status: str, changed_by_id: str):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.status in RESTRICTED_TRANSITIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order is already in terminal state: {order.status}")
        old_status = order.status
        order.status = new_status.upper()
        db.add(OrderStatusHistory(order_id=order.id, old_status=old_status, new_status=new_status.upper(), changed_by_id=changed_by_id))
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def cancel_order(db: AsyncSession, order_id: str, customer_id: str, reason: Optional[str] = None):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.status not in CANCELLABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot cancel order in '{order.status}' state")
        old_status = order.status
        order.status = "CANCELLED"
        db.add(OrderStatusHistory(
            order_id=order.id, old_status=old_status, new_status="CANCELLED",
            changed_by_id=customer_id, cancellation_reason=reason
        ))
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def get_status_history(db: AsyncSession, order_id: str):
        result = await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at.asc())
        )
        return result.scalars().all()
