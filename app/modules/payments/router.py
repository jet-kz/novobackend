from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.payments.service import PaymentService

router = APIRouter()


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def get_payment_for_order(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get payment status and details for a specific order."""
    payment = await PaymentService.get_by_order(db, order_id)
    return {"success": True, "message": "Payment retrieved", "data": payment}


@router.get("/verify/{reference}", status_code=status.HTTP_200_OK)
async def verify_payment(reference: str = Path(...), db: AsyncSession = Depends(get_db)):
    """Verify payment status directly with Paystack API and update order status."""
    res = await PaymentService.verify_paystack_transaction(db, reference)
    return {"success": True, "message": "Payment verified", "data": res}


@router.post("", status_code=status.HTTP_201_CREATED)
async def initiate_payment(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Initiate a payment record for an order. Returns payment id to reference when recording the transaction."""
    payment = await PaymentService.create(db, payload)
    return {"success": True, "message": "Payment initiated", "data": payment}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Paystack webhook callback endpoint for real-time payment event notifications."""
    event = payload.get("event")
    data = payload.get("data", {})
    
    if event == "charge.success":
        reference = data.get("reference")
        amount = data.get("amount", 0) / 100.0  # Convert kobo to Naira
        # Payment succeeded notification received from Paystack
        return {
            "status": True,
            "message": "Paystack charge.success webhook processed",
            "reference": reference,
            "amount": amount
        }
    
    return {"status": True, "message": f"Event '{event}' received successfully"}


@router.post("/{payment_id}/transactions", status_code=status.HTTP_201_CREATED)
async def record_transaction(payment_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Record a provider transaction (e.g. Paystack webhook callback). Marks payment as paid on success."""
    txn = await PaymentService.record_transaction(db, payment_id, payload)
    return {"success": True, "message": "Transaction recorded", "data": txn}


@router.post("/{payment_id}/refunds", status_code=status.HTTP_201_CREATED)
async def request_refund(payment_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Request a refund against a completed payment."""
    refund = await PaymentService.request_refund(db, payment_id, payload)
    return {"success": True, "message": "Refund requested", "data": refund}


@router.get("/{payment_id}/refunds", status_code=status.HTTP_200_OK)
async def list_refunds(payment_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """List all refunds on a given payment."""
    refunds = await PaymentService.get_refunds(db, payment_id)
    return {"success": True, "message": "Refunds retrieved", "data": refunds}


@router.patch("/{payment_id}/refunds/{refund_id}/process", status_code=status.HTTP_200_OK)
async def process_refund(payment_id: str = Path(...), refund_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(require_role("admin"))):
    """Admin only: Mark a refund as processed."""
    refund = await PaymentService.process_refund(db, refund_id)
    return {"success": True, "message": "Refund processed", "data": refund}
