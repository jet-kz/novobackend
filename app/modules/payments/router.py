from fastapi import APIRouter, Depends, status, Path, Body
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.payments.service import PaymentService
from app.modules.payments.bachs_service import BachsService

router = APIRouter()


@router.post("/bachs/checkout", status_code=status.HTTP_200_OK)
async def create_bachs_checkout(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a Bachs hosted checkout session for an order with optional vendor split payments."""
    order_id = payload.get("order_id")
    amount = float(payload.get("amount", 0))
    email = payload.get("email", current_user.get("email", "customer@novo.app"))
    splits = payload.get("splits")
    
    res = await BachsService.create_checkout_session(
        order_id=order_id,
        amount=amount,
        customer_email=email,
        splits=splits
    )
    return {"success": True, "data": res}


@router.post("/bachs/subaccount", status_code=status.HTTP_201_CREATED)
async def create_bachs_subaccount(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("merchant_owner"))
):
    """Register a merchant or rider bank subaccount on Bachs for automated split disbursements."""
    business_name = payload.get("business_name")
    bank_code = payload.get("bank_code")
    account_number = payload.get("account_number")
    email = payload.get("contact_email", current_user.get("email"))
    
    res = await BachsService.create_vendor_subaccount(
        business_name=business_name,
        bank_code=bank_code,
        account_number=account_number,
        contact_email=email
    )
    return {"success": True, "message": "Bachs vendor subaccount created", "data": res}


@router.post("/webhook/bachs", status_code=status.HTTP_200_OK)
async def bachs_webhook(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Bachs real-time payment webhook callback endpoint."""
    event = payload.get("event")
    data = payload.get("data", {})
    
    if event in ("payment.succeeded", "charge.success"):
        metadata = data.get("metadata", {})
        order_id = metadata.get("order_id")
        reference = data.get("reference")
        amount = data.get("amount", 0) / 100.0
        return {
            "status": True,
            "message": "Bachs payment succeeded webhook processed",
            "order_id": order_id,
            "reference": reference,
            "amount": amount
        }
    
    return {"status": True, "message": f"Bachs event '{event}' received successfully"}


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
