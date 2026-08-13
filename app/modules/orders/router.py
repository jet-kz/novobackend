from fastapi import APIRouter, Depends, status, Path, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.modules.orders.service import OrderService

router = APIRouter()


@router.get("", status_code=status.HTTP_200_OK)
async def list_orders(
    customer_id: Optional[str] = Query(None, description="Filter by customer (admin use)"),
    order_status: Optional[str] = Query(None, description="Filter by status e.g. PENDING, DELIVERED"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """List orders. Customers see only their own. Admins can filter by customer ID or status."""
    orders = await OrderService.get_all_orders(db, current_user=current_user, customer_id=customer_id, order_status=order_status)
    return {"success": True, "message": "Orders retrieved successfully", "data": orders}


@router.get("/{order_id}", status_code=status.HTTP_200_OK)
async def get_order(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get full details of a specific order including items and status history."""
    order = await OrderService.get_by_id(db, order_id)
    return {"success": True, "message": "Order retrieved", "data": order}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_order(payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Place a new order. Customer ID is automatically set from JWT."""
    order = await OrderService.create_order(db, current_user["user_id"], payload)
    return {"success": True, "message": "Order placed successfully", "data": order}


@router.patch("/{order_id}/status", status_code=status.HTTP_200_OK)
async def update_order_status(order_id: str = Path(...), payload: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Update an order's status (CONFIRMED, PREPARING, DISPATCHED, DELIVERED, CANCELLED)."""
    order = await OrderService.update_status(db, order_id, payload.get("status"), current_user["user_id"])
    return {"success": True, "message": f"Order status updated to {payload.get('status')}", "data": order}


@router.post("/{order_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_order(order_id: str = Path(...), payload: dict = Body(default={}), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Cancel an order. Only possible before it reaches DISPATCHED state."""
    order = await OrderService.cancel_order(db, order_id, current_user["user_id"], payload.get("reason"))
    return {"success": True, "message": "Order cancelled", "data": order}


@router.get("/{order_id}/history", status_code=status.HTTP_200_OK)
async def get_order_status_history(order_id: str = Path(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Get the full timeline of status changes for an order."""
    history = await OrderService.get_status_history(db, order_id)
    return {"success": True, "message": "Order history retrieved", "data": history}
