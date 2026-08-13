from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.payments.models import Payment, PaymentTransaction, Refund


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

        # Auto-update payment status
        if data.get("status") == "success":
            payment.status = "paid"
        elif data.get("status") == "failed":
            payment.status = "failed"

        await db.commit()
        await db.refresh(txn)
        return txn

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
