import json
import logging
import secrets
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, status, Path, Body, Request, HTTPException
from app.core import config
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user, get_optional_user, require_role
from app.modules.payments.service import PaymentService, valid_paystack_signature
from app.modules.orders.models import Order
from app.modules.orders.service import OrderService
from app.modules.orders.status import canonical_stored_status
from app.modules.payments.bachs_service import PAID_STATUSES, BachsService, verify_webhook_signature

router = APIRouter()
logger = logging.getLogger(__name__)


async def _order_for_payment(db: AsyncSession, payload: dict, user: Optional[dict]) -> Order:
    """The caller's order: by account, or by the guest token from checkout."""
    order_id = str(payload.get("order_id") or "")
    guest_token = str(payload.get("guest_token") or "")
    if guest_token:
        return await OrderService.load_guest_order(db, order_id, guest_token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in or use your order link to pay")
    return await PaymentService._owned_order(db, order_id, user)


def _return_urls(order: Order, guest_token: str) -> tuple[str, str]:
    base = config.FRONTEND_URL
    if guest_token:
        track = f"{base}/track/{quote(order.id)}?t={quote(guest_token)}"
        return f"{track}&paid=1", f"{track}&payment=cancelled"
    return f"{base}/orders?orderId={quote(order.id)}&paid=1", f"{base}/orders?orderId={quote(order.id)}&payment=cancelled"


@router.post("/bachs/checkout", status_code=status.HTTP_200_OK)
async def create_bachs_checkout(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_user),
):
    """Start Bachs hosted checkout for an unpaid card order; returns the URL to redirect the customer to."""
    order = await _order_for_payment(db, payload, user)
    if order.payment_status == "paid":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order is already paid")
    if canonical_stored_status(order.status) in ("CANCELLED", "FAILED"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order was cancelled")
    if order.payment_method != "card":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This order is paid on delivery")

    success_url, cancel_url = _return_urls(order, str(payload.get("guest_token") or ""))
    session = await BachsService.create_checkout_session(
        order_id=order.id,
        amount=float(order.total),  # never a client-sent amount
        currency=order.currency or "NGN",
        reference=f"{order.id}-{secrets.token_hex(3)}",  # unique per attempt so retries work
        customer_email=order.customer_email,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    await PaymentService._get_or_create_payment(db, order)
    await db.commit()
    return {"success": True, "data": session}


@router.post("/bachs/confirm", status_code=status.HTTP_200_OK)
async def confirm_bachs_checkout(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[dict] = Depends(get_optional_user),
):
    """
    Called when the customer lands back from Bachs. Asks Bachs about the session and records the
    payment if it is complete; otherwise the webhook will. Returns the order's payment_status.
    """
    order = await _order_for_payment(db, payload, user)
    checkout_id = str(payload.get("checkout_id") or "")
    if order.payment_status != "paid" and checkout_id:
        session = await BachsService.get_checkout_session(checkout_id) or {}
        meta = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
        payment = session.get("payment") if isinstance(session.get("payment"), dict) else {}
        paid = str(payment.get("status") or session.get("payment_status") or "").lower() in PAID_STATUSES
        if meta.get("order_id") == order.id and paid:
            try:
                await PaymentService.apply_bachs_collection(db, {
                    "metadata": meta,
                    "amount": payment.get("amount") or session.get("amount"),
                    "currency": payment.get("currency") or session.get("currency"),
                    "charge_id": payment.get("charge_id") or payment.get("id"),
                    "checkout_id": checkout_id,
                })
            except HTTPException as exc:
                logger.warning("Bachs confirm not applied for %s: %s", order.id, exc.detail)
            await db.refresh(order)
    return {"success": True, "data": {"order_id": order.id, "payment_status": order.payment_status}}


@router.post("/webhook/bachs", status_code=status.HTTP_200_OK)
async def bachs_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Bachs webhook (register this URL in the Bachs dashboard). Signature is HMAC-SHA256 of "{timestamp}.{body}"."""
    raw = await request.body()
    if not verify_webhook_signature(raw, request.headers):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        event = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    kind = event.get("type")
    data = event.get("data") or {}
    if kind == "collection.succeeded":
        try:
            result = await PaymentService.apply_bachs_collection(db, data)
            return {"received": True, "order_id": result.get("order_id")}
        except HTTPException as exc:
            # Acknowledge so Bachs stops retrying; logged for manual reconciliation.
            logger.warning("Bachs webhook %s not applied: %s", event.get("id"), exc.detail)
            return {"received": True, "applied": False, "reason": exc.detail}
    if kind in ("collection.underpaid", "collection.failed"):
        logger.warning("Bachs %s for order %s", kind, (data.get("metadata") or {}).get("order_id"))
    elif kind in ("account.updated", "capability.updated", "transfer.created", "payout.paid", "payout.failed"):
        from app.modules.payouts.service import PayoutService

        await PayoutService.handle_event(db, kind, data, event.get("account"))
    return {"received": True}


@router.get("/verify/{reference}", status_code=status.HTTP_200_OK)
async def verify_payment(reference: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Verify a card payment with Paystack and mark the caller's order paid if the full amount was charged."""
    res = await PaymentService.verify_paystack_transaction(db, reference, current_user)
    return {"success": bool(res.get("verified")), "message": "Payment verified" if res.get("verified") else res.get("message"), "data": res}


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def get_payment_for_order(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get payment status and details for one of the caller's orders."""
    payment = await PaymentService.get_by_order(db, order_id, current_user)
    return {"success": True, "message": "Payment retrieved", "data": payment}


@router.post("", status_code=status.HTTP_201_CREATED)
async def initiate_payment(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Open the payment record for one of the caller's orders. Amount is taken from the order."""
    payment = await PaymentService.create(db, payload, current_user)
    return {"success": True, "message": "Payment initiated", "data": payment}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Paystack webhook. The x-paystack-signature header must be a valid HMAC-SHA512 of the raw body."""
    raw = await request.body()
    if not valid_paystack_signature(raw, request.headers.get("x-paystack-signature", ""), config.PAYSTACK_SECRET_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event = payload.get("event")
    data = payload.get("data") or {}
    if event == "charge.success" and data.get("reference"):
        try:
            result = await PaymentService.apply_successful_charge(db, data["reference"], data)
            return {"status": True, "message": "charge.success processed", "order_id": result.get("order_id")}
        except HTTPException as exc:
            # Acknowledge so Paystack stops retrying; the mismatch is logged for reconciliation.
            logger.warning("Paystack webhook not applied for %s: %s", data.get("reference"), exc.detail)
            return {"status": True, "message": f"Not applied: {exc.detail}"}
    return {"status": True, "message": f"Event '{event}' received"}


@router.post("/{payment_id}/transactions", status_code=status.HTTP_201_CREATED)
async def record_transaction(payment_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin: record a manual/offline transaction (e.g. confirmed bank transfer). Marks payment paid on success."""
    txn = await PaymentService.record_transaction(db, payment_id, payload)
    return {"success": True, "message": "Transaction recorded", "data": txn}


@router.post("/{payment_id}/refunds", status_code=status.HTTP_201_CREATED)
async def request_refund(payment_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Request a refund against a completed payment."""
    refund = await PaymentService.request_refund(db, payment_id, payload, current_user)
    return {"success": True, "message": "Refund requested", "data": refund}


@router.get("/{payment_id}/refunds", status_code=status.HTTP_200_OK)
async def list_refunds(payment_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """List all refunds on a given payment."""
    refunds = await PaymentService.get_refunds(db, payment_id, current_user)
    return {"success": True, "message": "Refunds retrieved", "data": refunds}


@router.patch("/{payment_id}/refunds/{refund_id}/process", status_code=status.HTTP_200_OK)
async def process_refund(payment_id: str = Path(...), refund_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin only: Mark a refund as processed."""
    refund = await PaymentService.process_refund(db, refund_id)
    return {"success": True, "message": "Refund processed", "data": refund}
