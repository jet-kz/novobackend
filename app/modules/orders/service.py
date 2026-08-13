from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status
from app.modules.orders.models import Order, OrderStatusHistory
from typing import Optional


CANCELLABLE_STATUSES = {"CART", "PENDING", "CONFIRMED"}
RESTRICTED_TRANSITIONS = {"DISPATCHED", "DELIVERED", "FAILED", "CANCELLED"}


class OrderService:
    @staticmethod
    async def get_all_orders(db: AsyncSession, current_user: dict, customer_id: Optional[str] = None, order_status: Optional[str] = None):
        stmt = select(Order)
        is_admin = "admin" in current_user.get("roles", [])
        if not is_admin:
            stmt = stmt.where(Order.customer_id == current_user["user_id"])
        elif customer_id:
            stmt = stmt.where(Order.customer_id == customer_id)
        if order_status:
            stmt = stmt.where(Order.status == order_status.upper())
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(db: AsyncSession, order_id: str):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        return order

    @staticmethod
    async def create_order(db: AsyncSession, customer_id: str, data: dict):
        data["customer_id"] = customer_id
        data["status"] = "PENDING"
        order = Order(**data)
        db.add(order)
        await db.flush()
        # log initial status event
        history = OrderStatusHistory(
            order_id=order.id, old_status=None, new_status="PENDING", changed_by_id=customer_id
        )
        db.add(history)
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def update_status(db: AsyncSession, order_id: str, new_status: str, changed_by_id: str):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.status in RESTRICTED_TRANSITIONS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order is already in terminal state: {order.status}")
        old_status = order.status
        order.status = new_status.upper()
        db.add(OrderStatusHistory(order_id=order.id, old_status=old_status, new_status=new_status.upper(), changed_by_id=changed_by_id))
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def cancel_order(db: AsyncSession, order_id: str, customer_id: str, reason: Optional[str] = None):
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if order.status not in CANCELLABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot cancel order in '{order.status}' state")
        old_status = order.status
        order.status = "CANCELLED"
        db.add(OrderStatusHistory(
            order_id=order.id, old_status=old_status, new_status="CANCELLED",
            changed_by_id=customer_id, cancellation_reason=reason
        ))
        await db.commit()
        await db.refresh(order)
        return order

    @staticmethod
    async def get_status_history(db: AsyncSession, order_id: str):
        result = await db.execute(
            select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.created_at.asc())
        )
        return result.scalars().all()
