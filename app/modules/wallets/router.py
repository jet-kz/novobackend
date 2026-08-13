from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.modules.wallets.service import WalletService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def get_my_wallets(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all wallets for the authenticated user (one per currency)."""
    wallets = await WalletService.get_wallets(db, current_user["user_id"])
    return {"success": True, "message": "Wallets retrieved", "data": wallets}


@router.get("/{currency}/balance", status_code=status.HTTP_200_OK)
async def get_balance(currency: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get wallet balance for a specific currency."""
    wallet = await WalletService.get_wallet(db, current_user["user_id"], currency.upper())
    return {"success": True, "message": f"{currency.upper()} wallet balance", "data": wallet}


@router.get("/{currency}/transactions", status_code=status.HTTP_200_OK)
async def get_transactions(currency: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get all ledger transactions for a specific currency wallet."""
    transactions = await WalletService.get_transactions(db, current_user["user_id"], currency.upper())
    return {"success": True, "message": "Wallet transactions retrieved", "data": transactions}


@router.post("/credit", status_code=status.HTTP_200_OK)
async def credit_wallet(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Credit funds to a user wallet (e.g., top-up, refund credit)."""
    wallet = await WalletService.credit(db, current_user["user_id"], payload)
    return {"success": True, "message": "Wallet credited successfully", "data": wallet}


@router.post("/debit", status_code=status.HTTP_200_OK)
async def debit_wallet(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Debit funds from a user wallet (e.g., purchase payment, withdrawal)."""
    wallet = await WalletService.debit(db, current_user["user_id"], payload)
    return {"success": True, "message": "Wallet debited successfully", "data": wallet}
