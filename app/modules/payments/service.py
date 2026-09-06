import os
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.payments.models import Payment, PaymentTransaction, Refund
from app.modules.orders.models import Order

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "sk_test_c816d68a9a784dadcc2a1f8c76af63c238600d76")


class PaymentService:
    @staticmethod
    async def get_by_order(db: AsyncSession, order_id: str):
        result = await db.execute(select(Payment).where(Payment.order_id == order_id))
        payment = result.scalar_one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No payment found for this order")
        return payment

    @staticmethod
    async def create(db: AsyncSession, data: dict):
        payment = Payment(**data)
        db.add(payment)
        await db.commit()
        await db.refresh(payment)
        return payment

    @staticmethod
    async def record_transaction(db: AsyncSession, payment_id: str, data: dict):
        result = await db.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

        data["payment_id"] = payment_id
        txn = PaymentTransaction(**data)
        db.add(txn)

        # Auto-update payment status & order payment_status
        if data.get("status") == "success":
            payment.status = "paid"
            # Update corresponding order status
            order_res = await db.execute(select(Order).where(Order.id == payment.order_id))
            order = order_res.scalar_one_or_none()
            if order:
                order.payment_status = "paid"
                order.status = "PLACED"
        elif data.get("status") == "failed":
            payment.status = "failed"

        await db.commit()
        await db.refresh(txn)
        return txn

    @staticmethod
    async def verify_paystack_transaction(db: AsyncSession, reference: str):
        """Verify transaction with Paystack official REST API."""
        url = f"https://api.paystack.co/transaction/verify/{reference}"
        headers = {
            "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to connect to Paystack: {str(e)}")

        if response.status_code != 200:
            res_json = response.json() if response.content else {}
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=res_json.get("message", "Paystack verification request failed")
            )

        res_data = response.json()
        if not res_data.get("status") or res_data.get("data", {}).get("status") != "success":
            return {
                "verified": False,
                "status": res_data.get("data", {}).get("status", "failed"),
                "message": "Payment was not completed successfully"
            }

        paystack_data = res_data["data"]
        amount = paystack_data.get("amount", 0) / 100.0

        target_order_id = reference

        # Sync Payment & Order in Database
        payment_res = await db.execute(select(Payment).where((Payment.id == reference) | (Payment.order_id == reference)))
        payment = payment_res.scalar_one_or_none()

        if payment:
            payment.status = "paid"
            target_order_id = payment.order_id
            order_res = await db.execute(select(Order).where(Order.id == payment.order_id))
            order = order_res.scalar_one_or_none()
            if order:
                order.payment_status = "paid"
                order.status = "PLACED"
        else:
            order_res = await db.execute(select(Order).where(Order.id == reference))
            order = order_res.scalar_one_or_none()
            if order:
                order.payment_status = "paid"
                order.status = "PLACED"

        # Record Immutable Financial Ledger Split if PricingSnapshot exists
        from app.modules.pricing.models import PricingSnapshot
        from app.modules.payments.ledger import LedgerService

        snap_res = await db.execute(select(PricingSnapshot).where(PricingSnapshot.order_id == target_order_id))
        snapshot = snap_res.scalar_one_or_none()

        if snapshot:
            merchant_id = str(order.store_id) if (order and order.store_id) else None
            await LedgerService.record_payment_ledger_split(
                db, target_order_id, merchant_id, None, snapshot, reference
            )

        await db.commit()

        return {
            "verified": True,
            "status": "success",
            "reference": reference,
            "amount": amount,
            "paystack_data": paystack_data
        }

    @staticmethod
    async def request_refund(db: AsyncSession, payment_id: str, data: dict):
        result = await db.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
        if not payment or payment.status != "paid":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment must be in paid status to request refund")

        data["payment_id"] = payment_id
        refund = Refund(**data)
        db.add(refund)
        await db.commit()
        await db.refresh(refund)
        return refund

    @staticmethod
    async def get_refunds(db: AsyncSession, payment_id: str):
        result = await db.execute(select(Refund).where(Refund.payment_id == payment_id))
        return result.scalars().all()

    @staticmethod
    async def process_refund(db: AsyncSession, refund_id: str):
        result = await db.execute(select(Refund).where(Refund.id == refund_id))
        refund = result.scalar_one_or_none()
        if not refund:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Refund not found")
        refund.status = "processed"
        await db.commit()
        await db.refresh(refund)
        return refund
