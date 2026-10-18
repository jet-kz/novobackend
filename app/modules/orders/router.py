from fastapi import APIRouter, Depends, status, Path, Body, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.orders.service import OrderService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_orders(
    store_id: Optional[str] = Query(None, description="Filter by store ID"),
    customer_id: Optional[str] = Query(None, description="Filter by customer (admin use)"),
    order_status: Optional[str] = Query(None, description="Filter by status e.g. PENDING, DELIVERED"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List orders with merchant/customer multi-tenant isolation."""
    orders = await OrderService.get_all_orders(db, current_user=current_user, store_id=store_id, customer_id=customer_id, order_status=order_status)
    return {"success": True, "message": "Orders retrieved successfully", "data": orders}


# ── Guest checkout (no account) ──────────────────────────────────────────────
# Guests get a secret token at checkout; it goes in their tracking link and is required to
# view, pay for or cancel the order.

@router.post("/guest/quote", status_code=status.HTTP_200_OK)
async def quote_guest_order(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Price a guest cart. Promo codes need an account."""
    quote = await OrderService.quote_guest(db, payload)
    return {"success": True, "message": "Quote calculated", "data": quote}


@router.post("/guest", status_code=status.HTTP_201_CREATED)
async def create_guest_order(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """Place an order without an account. Requires customer_name and customer_phone; customer_email is optional (receipts)."""
    order = await OrderService.create_guest_order(db, payload)
    return {"success": True, "message": "Order placed successfully", "data": order}


@router.get("/guest/{order_id}", status_code=status.HTTP_200_OK)
async def get_guest_order(order_id: str = Path(...), token: str = Query(...), db: AsyncSession = Depends(get_db)):
    order = await OrderService.get_guest_order(db, order_id, token)
    return {"success": True, "message": "Order retrieved", "data": order}


@router.post("/guest/{order_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_guest_order(order_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    order = await OrderService.cancel_guest_order(db, order_id, str(payload.get("token") or ""), payload.get("reason"))
    return {"success": True, "message": "Order cancelled", "data": order}


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def get_order(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get full details of a specific order including items and status history."""
    order = await OrderService.get_by_id(db, order_id, current_user)
    return {"success": True, "message": "Order retrieved", "data": order}


@router.post("/quote", status_code=status.HTTP_200_OK)
async def quote_order(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Price a cart exactly as order creation would, without saving. Use this for the checkout summary."""
    quote = await OrderService.quote(db, current_user, payload)
    return {"success": True, "message": "Quote calculated", "data": quote}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Place a new order. Prices, fees and totals are computed server-side; customer is taken from the JWT."""
    order = await OrderService.create_order(db, current_user, payload)
    return {"success": True, "message": "Order placed successfully", "data": order}


@router.patch("/{order_id}/status", status_code=status.HTTP_200_OK)
async def update_order_status(
    order_id: str = Path(...),
    status_param: Optional[str] = Query(None, alias="status"),
    payload: Optional[dict] = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Move an order through its lifecycle. Merchants confirm/prepare/ready/cancel their store's orders;
    riders accept/pick up (with pickup_code)/deliver their jobs; admins can make any valid move.
    """
    body = payload if isinstance(payload, dict) else {}
    new_status = body.get("status") or status_param
    if not new_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Status is required")
    order = await OrderService.update_status(db, order_id, new_status, current_user, body)
    return {"success": True, "message": f"Order status updated to {order['status']}", "data": order}


@router.post("/{order_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_order(order_id: str = Path(...), payload: Optional[dict] = Body(default=None), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Customer: cancel your own order before the store starts preparing it."""
    order = await OrderService.cancel_order(db, order_id, current_user, (payload or {}).get("reason"))
    return {"success": True, "message": "Order cancelled", "data": order}


@router.get("/{order_id}/history", status_code=status.HTTP_200_OK)
async def get_order_status_history(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get the full timeline of status changes for an order."""
    history = await OrderService.get_status_history(db, order_id, current_user)
    return {"success": True, "message": "Order history retrieved", "data": history}
