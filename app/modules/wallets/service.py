from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.wallets.models import Wallet, WalletTransaction


def _positive_amount(data: dict) -> float:
    try:
        amount = round(float((data or {}).get("amount", 0)), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be a number")
    if amount <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be greater than zero")
    return amount


class WalletService:
    @staticmethod
    async def get_wallets(db: AsyncSession, holder_id: str):
        result = await db.execute(select(Wallet).where(Wallet.holder_id == holder_id))
        return result.scalars().all()

    @staticmethod
    async def get_wallet(db: AsyncSession, holder_id: str, currency: str):
        result = await db.execute(
            select(Wallet).where(Wallet.holder_id == holder_id, Wallet.currency == currency)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            return await WalletService._get_or_create_wallet(db, holder_id, currency)
        return wallet

    @staticmethod
    async def _get_or_create_wallet(db: AsyncSession, holder_id: str, currency: str):
        result = await db.execute(
            select(Wallet).where(Wallet.holder_id == holder_id, Wallet.currency == currency)
        )
        wallet = result.scalar_one_or_none()
        if not wallet:
            wallet = Wallet(holder_id=holder_id, currency=currency, balance=0.0)
            db.add(wallet)
            await db.commit()
            await db.refresh(wallet)
        return wallet

    @staticmethod
    async def get_transactions(db: AsyncSession, holder_id: str, currency: str):
        wallet = await WalletService.get_wallet(db, holder_id, currency)
        if not wallet:
            return []
        result = await db.execute(
            select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
            .order_by(WalletTransaction.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def credit(db: AsyncSession, holder_id: str, data: dict):
        currency = str(data.get("currency") or "NGN").upper()
        amount = _positive_amount(data)
        wallet = await WalletService._get_or_create_wallet(db, holder_id, currency)
        wallet.balance += amount
        txn = WalletTransaction(
            wallet_id=wallet.id,
            amount=amount,
            direction="credit",
            txn_type=data.get("txn_type", "payment"),
            reference=data.get("reference")
        )
        db.add(txn)
        await db.commit()
        await db.refresh(wallet)
        return wallet

    @staticmethod
    async def debit(db: AsyncSession, holder_id: str, data: dict):
        currency = str(data.get("currency") or "NGN").upper()
        amount = _positive_amount(data)
        await WalletService._get_or_create_wallet(db, holder_id, currency)
        # Lock the row so two concurrent payouts cannot both pass the balance check.
        locked = await db.execute(
            select(Wallet).where(Wallet.holder_id == holder_id, Wallet.currency == currency).with_for_update()
        )
        wallet = locked.scalar_one()
        if wallet.balance < amount:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Insufficient wallet balance")
        wallet.balance -= amount
        txn = WalletTransaction(
            wallet_id=wallet.id,
            amount=amount,
            direction="debit",
            txn_type=data.get("txn_type", "payment"),
            reference=data.get("reference")
        )
        db.add(txn)
        await db.commit()
        await db.refresh(wallet)
        return wallet
