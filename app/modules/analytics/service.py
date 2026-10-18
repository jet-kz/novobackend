from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException, status
from app.modules.orders.models import Order
from app.modules.stores.models import Store
from app.modules.riders.models import RiderProfile
from typing import Optional
from app.modules.merchants.models import Merchant


class AnalyticsService:
    @staticmethod
    def _gmv_today(orders_paid) -> float:
        today = datetime.now(timezone.utc).date()
        total = 0.0
        for order in orders_paid:
            created = getattr(order, "created_at", None)
            if not created:
                continue
            created_date = created.date() if hasattr(created, "date") else None
            if created_date == today:
                total += float(order.total or 0)
        return total

    @staticmethod
    async def get_analytics(db: AsyncSession, current_user: Optional[dict] = None):
        roles = (current_user or {}).get("roles", [])
        is_admin = "admin" in roles or "super_admin" in roles
        merchant_store_ids = []

        if current_user and not is_admin:
            merch_res = await db.execute(
                select(Merchant).where(Merchant.owner_id == current_user["user_id"], Merchant.is_deleted == False)
            )
            merchant = merch_res.scalar_one_or_none()
            if merchant:
                stores_res = await db.execute(
                    select(Store.id).where(Store.merchant_id == merchant.id, Store.is_deleted == False)
                )
                merchant_store_ids = list(stores_res.scalars().all())
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Analytics are limited to merchants and administrators",
                )

        if merchant_store_ids:
            rev_result = await db.execute(
                select(Order).filter(Order.store_id.in_(merchant_store_ids), Order.payment_status == "paid")
            )
            orders_paid = rev_result.scalars().all()
            revenue = sum(o.total for o in orders_paid)

            orders_count_result = await db.execute(
                select(func.count(Order.id)).filter(Order.store_id.in_(merchant_store_ids))
            )
            total_orders = orders_count_result.scalar() or 0

            return {
                "totalRevenue": revenue,
                "totalOrders": total_orders,
                "activeStoresCount": len(merchant_store_ids),
                "activeRidersCount": 0,
                "totalCustomersCount": len(set(o.customer_id for o in orders_paid)),
                "gmvToday": AnalyticsService._gmv_today(orders_paid),
                "commissionEarned": revenue * 0.15,
            }

        rev_result = await db.execute(select(Order).filter(Order.payment_status == "paid"))
        orders_paid = rev_result.scalars().all()
        revenue = sum(o.total for o in orders_paid)

        orders_count_result = await db.execute(select(func.count(Order.id)))
        total_orders = orders_count_result.scalar() or 0

        stores_count_result = await db.execute(select(func.count(Store.id)).filter(Store.is_deleted == False))
        active_stores = stores_count_result.scalar() or 0

        riders_count_result = await db.execute(
            select(func.count(RiderProfile.id)).filter(RiderProfile.status == "online", RiderProfile.is_deleted == False)
        )
        active_riders = riders_count_result.scalar() or 0

        customer_ids_result = await db.execute(select(Order.customer_id).distinct())
        customers_count = len(customer_ids_result.scalars().all())

        return {
            "totalRevenue": revenue,
            "totalOrders": total_orders,
            "activeStoresCount": active_stores,
            "activeRidersCount": active_riders,
            "totalCustomersCount": customers_count,
            "gmvToday": AnalyticsService._gmv_today(orders_paid),
            "commissionEarned": revenue * 0.15,
        }
