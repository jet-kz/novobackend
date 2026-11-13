import hashlib
import hmac
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.core import config
from app.core.access import is_admin, to_uuid
from app.modules.payments.models import Payment, PaymentTransaction, Refund
from app.modules.orders.models import Order
from app.modules.notifications import service as notify

logger = logging.getLogger(__name__)


def order_id_from_reference(reference: str) -> str:
    """Checkout uses `<order_id>_<timestamp>` so a retried payment gets a fresh Paystack reference."""
    return (reference or "").split("_", 1)[0]


def amount_covers_order(paid_kobo: int, order_total: float) -> bool:
    return int(paid_kobo or 0) >= int(round(float(order_total or 0) * 100))


def valid_paystack_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


class PaymentService:
    @staticmethod
    async def _owned_order(db: AsyncSession, order_id: str, current_user: dict) -> Order:
        order = await db.get(Order, order_id) if order_id else None
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.customer_id != current_user["user_id"] and not is_admin(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this order")
        return order

    @staticmethod
    async def get_by_order(db: AsyncSession, order_id: str, current_user: dict):
        await PaymentService._owned_order(db, order_id, current_user)
        result = await db.execute(
            select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.desc())
        )
        payment = result.scalars().first()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No payment found for this order")
        return payment

    @staticmethod
    async def _get_or_create_payment(db: AsyncSession, order: Order) -> Payment:
        result = await db.execute(
            select(Payment).where(Payment.order_id == order.id).order_by(Payment.created_at.desc())
        )
        payment = result.scalars().first()
        if payment:
            return payment
        payment = Payment(order_id=order.id, amount=float(order.total), currency=order.currency or "NGN", status="pending")
        db.add(payment)
        await db.flush()
        return payment

    @staticmethod
    async def create(db: AsyncSession, data: dict, current_user: dict):
        """Open (or return) the payment record for an order. The amount always comes from the order."""
        order = await PaymentService._owned_order(db, str((data or {}).get("order_id") or ""), current_user)
        payment = await PaymentService._get_or_create_payment(db, order)
        await db.commit()
        await db.refresh(payment)
        return payment

    @staticmethod
    async def record_transaction(db: AsyncSession, payment_id: str, data: dict):
        """Admin/manual reconciliation only. Customer card payments are confirmed via Paystack verification."""
        result = await db.execute(select(Payment).where(Payment.id == to_uuid(payment_id, "payment_id")))
        payment = result.scalar_one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        reference = str(data.get("provider_reference") or data.get("provider_tx_id") or "").strip()
        if not reference:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider_reference is required")
        txn_status = data.get("status") or "success"
        txn = PaymentTransaction(
            payment_id=payment.id,
            txn_type=data.get("txn_type") or "charge",
            provider=data.get("provider") or "manual",
            provider_reference=reference,
            amount=float(data.get("amount") or payment.amount),
            currency=data.get("currency") or payment.currency,
            status=txn_status,
            provider_metadata=data.get("provider_metadata") or data.get("raw_response"),
        )
        db.add(txn)
        if txn_status == "success":
            payment.status = "paid"
            order = await db.get(Order, payment.order_id)
            if order:
                order.payment_status = "paid"
        elif txn_status == "failed":
            payment.status = "failed"
        await db.commit()
        await db.refresh(txn)
        return txn

    @staticmethod
    async def apply_successful_charge(db: AsyncSession, reference: str, paystack_data: dict) -> dict:
        """
        Idempotently mark an order paid from a Paystack charge. Shared by /verify and the webhook.
        Rejects charges smaller than the order total. The order status is not changed: the merchant
        still has to accept it.
        """
        metadata = paystack_data.get("metadata") if isinstance(paystack_data.get("metadata"), dict) else {}
        order_id = metadata.get("order_id") or order_id_from_reference(reference)
        order = await db.get(Order, order_id) if order_id else None
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No order matches this payment reference")

        paid_kobo = int(paystack_data.get("amount") or 0)
        if not amount_covers_order(paid_kobo, order.total):
            logger.warning("Underpayment for %s: paid %s kobo, order total %s", order.id, paid_kobo, order.total)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment amount does not match the order total")
        if str(paystack_data.get("currency") or "NGN").upper() != (order.currency or "NGN").upper():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment currency does not match the order")

        return await PaymentService.record_charge(
            db, order,
            amount=paid_kobo / 100.0,
            currency=order.currency or "NGN",
            provider="paystack",
            reference=reference,
            provider_metadata={
                "id": paystack_data.get("id"),
                "channel": paystack_data.get("channel"),
                "paid_at": paystack_data.get("paid_at"),
            },
        )

    @staticmethod
    async def record_charge(
        db: AsyncSession, order: Order, *, amount: float, currency: str, provider: str,
        reference: str, provider_metadata: dict | None = None,
    ) -> dict:
        """
        Idempotently mark an order paid. Every provider (Paystack, Bachs) ends here.
        Callers must already have checked amount and currency against the order.
        """
        from app.modules.payments.refunds import schedule_auto_refund

        result = {"verified": True, "status": "success", "reference": reference, "order_id": order.id, "amount": amount}
        metadata = dict(provider_metadata or {})
        existing = (await db.execute(select(PaymentTransaction).where(PaymentTransaction.provider_reference == reference))).scalar_one_or_none()
        if existing and existing.status == "underpaid":
            # A short payment that the customer has since topped up: drop the short record, record it in full below.
            await db.delete(existing)
            await db.flush()
        elif existing:
            return {**result, "already_recorded": True}

        payment = await PaymentService._get_or_create_payment(db, order)
        prior = (await db.execute(select(PaymentTransaction).where(
            PaymentTransaction.payment_id == payment.id, PaymentTransaction.txn_type == "charge",
            PaymentTransaction.status == "success",
        ))).scalars().all()
        if prior or order.payment_status in ("paid", "refund_pending", "refunded", "partially_refunded"):
            # The order is already paid. The same payment reported twice (webhook and return page) has the
            # same checkout; a different checkout means the customer really paid twice -> refund the extra.
            checkout_id = metadata.get("checkout_id")
            seen = {(t.provider_metadata or {}).get("checkout_id") for t in prior if isinstance(t.provider_metadata, dict)}
            if provider == "bachs" and checkout_id and prior and checkout_id not in seen:
                db.add(PaymentTransaction(
                    payment_id=payment.id, txn_type="charge", provider=provider, provider_reference=reference,
                    amount=amount, currency=currency, status="duplicate", provider_metadata=metadata,
                ))
                await db.commit()
                logger.warning("Second payment for %s (%s); refunding it", order.id, reference)
                schedule_auto_refund(order.id, "duplicate_payment", reference=reference)
                return {**result, "duplicate": True}
            return {**result, "already_recorded": True}

        total = float(order.total or 0)
        if amount > total + 0.005:
            metadata["overpaid_by"] = round(amount - total, 2)
        payment.status = "paid"
        db.add(PaymentTransaction(
            payment_id=payment.id,
            txn_type="charge",
            provider=provider,
            provider_reference=reference,
            amount=amount,
            currency=currency,
            status="success",
            provider_metadata=metadata,
        ))
        order.payment_status = "paid"
        if order.status in ("CANCELLED", "FAILED"):
            # Paid after the order was cancelled (e.g. checkout left open): give it straight back.
            await db.commit()
            schedule_auto_refund(order.id, "late_payment")
            return {**result, "late_payment": True}

        from app.modules.pricing.models import PricingSnapshot
        from app.modules.payments.ledger import LedgerService

        snap_res = await db.execute(select(PricingSnapshot).where(PricingSnapshot.order_id == order.id))
        snapshot = snap_res.scalar_one_or_none()
        if snapshot:
            await LedgerService.record_payment_ledger_split(
                db, order.id, str(order.store_id) if order.store_id else None, None, snapshot, reference
            )
        await db.commit()
        notify.payment_received(order.id, amount)
        return result

    @staticmethod
    async def apply_bachs_collection(db: AsyncSession, data: dict) -> dict:
        """Record a Bachs `collection.succeeded` payload (or a paid checkout session) against its order."""
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        order_id = metadata.get("order_id")
        order = await db.get(Order, order_id) if order_id else None
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No order matches this payment")
        currency = str(data.get("currency") or "").upper()
        try:
            amount = float(data.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if currency != (order.currency or "NGN").upper():
            # Bachs can let a buyer pay in another currency; we only fulfil NGN collections automatically.
            logger.warning("Bachs collection for %s in %s, order is %s", order.id, currency, order.currency)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment currency does not match the order")
        if amount + 0.005 < float(order.total or 0):
            logger.warning("Bachs underpayment for %s: %s < %s", order.id, amount, order.total)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment amount does not match the order total")
        reference = str(data.get("charge_id") or data.get("payment_id") or data.get("checkout_id") or "")
        if not reference:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment has no reference")
        return await PaymentService.record_charge(
            db, order, amount=amount, currency=currency, provider="bachs", reference=f"bachs:{reference}",
            provider_metadata={k: data.get(k) for k in ("checkout_id", "charge_id", "settlement_amount", "settlement_currency")},
        )

    @staticmethod
    async def verify_paystack_transaction(db: AsyncSession, reference: str, current_user: dict):
        """Verify a charge with Paystack's API, then record it against the caller's order."""
        if not config.PAYSTACK_SECRET_KEY:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Card payments are not configured on the server")
        await PaymentService._owned_order(db, order_id_from_reference(reference), current_user)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.paystack.co/transaction/verify/{reference}",
                    headers={"Authorization": f"Bearer {config.PAYSTACK_SECRET_KEY}"},
                    timeout=10.0,
                )
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to connect to Paystack: {e}")

        res_json = response.json() if response.content else {}
        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=res_json.get("message", "Paystack verification request failed"))
        data = res_json.get("data") or {}
        if not res_json.get("status") or data.get("status") != "success":
            return {"verified": False, "status": data.get("status", "failed"), "message": "Payment was not completed successfully"}
        return await PaymentService.apply_successful_charge(db, reference, data)

    @staticmethod
    async def _owned_payment(db: AsyncSession, payment_id: str, current_user: dict) -> Payment:
        result = await db.execute(select(Payment).where(Payment.id == to_uuid(payment_id, "payment_id")))
        payment = result.scalar_one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
        await PaymentService._owned_order(db, payment.order_id, current_user)
        return payment

    @staticmethod
    async def get_refunds(db: AsyncSession, payment_id: str, current_user: dict):
        payment = await PaymentService._owned_payment(db, payment_id, current_user)
        result = await db.execute(select(Refund).where(Refund.payment_id == payment.id))
        return result.scalars().all()

    @staticmethod
    async def apply_bachs_short_payment(db: AsyncSession, data: dict) -> None:
        """
        `collection.underpaid`: the customer sent less than the order total. The order stays unpaid;
        we keep a record of the money so it shows in the admin refunds queue. If the customer tops
        it up, the later `collection.succeeded` for the same charge replaces this record.
        """
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        order = await db.get(Order, metadata.get("order_id")) if metadata.get("order_id") else None
        reference = str(data.get("charge_id") or data.get("payment_id") or data.get("checkout_id") or "")
        if not order or not reference:
            return
        reference = f"bachs:{reference}"
        if (await db.execute(select(PaymentTransaction.id).where(PaymentTransaction.provider_reference == reference))).first():
            return
        try:
            amount = float(data.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            return
        payment = await PaymentService._get_or_create_payment(db, order)
        db.add(PaymentTransaction(
            payment_id=payment.id, txn_type="charge", provider="bachs", provider_reference=reference, amount=amount,
            currency=str(data.get("currency") or order.currency or "NGN").upper(), status="underpaid",
            provider_metadata={k: data.get(k) for k in ("checkout_id", "charge_id", "settlement_amount", "settlement_currency")},
        ))
        await db.commit()
        notify.short_payment(order.id, amount, order.total)
