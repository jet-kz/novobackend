from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.modules.orders.models import Order
from app.modules.stores.models import Store
from app.modules.riders.models import RiderProfile

from typing import Optional
from app.modules.merchants.models import Merchant

class AnalyticsService:
    @staticmethod
    async def get_analytics(db: AsyncSession, current_user: Optional[dict] = None):
        merchant_store_ids = []
        if current_user and "admin" not in current_user.get("roles", []):
            merch_res = await db.execute(select(Merchant).where(Merchant.owner_id == current_user["user_id"], Merchant.is_deleted == False))
            merchant = merch_res.scalar_one_or_none()
            if merchant:
                stores_res = await db.execute(select(Store.id).where(Store.merchant_id == merchant.id, Store.is_deleted == False))
                merchant_store_ids = list(stores_res.scalars().all())

        if merchant_store_ids:
            rev_result = await db.execute(
                select(Order).filter(Order.store_id.in_(merchant_store_ids), Order.payment_status == "paid")
            )
            orders_paid = rev_result.scalars().all()
            revenue = sum(o.total for o in orders_paid)

            orders_count_result = await db.execute(select(func.count(Order.id)).filter(Order.store_id.in_(merchant_store_ids)))
            total_orders = orders_count_result.scalar() or 0

            return {
                "totalRevenue": revenue,
                "totalOrders": total_orders,
                "activeStoresCount": len(merchant_store_ids),
                "activeRidersCount": 0,
                "totalCustomersCount": len(set(o.customer_id for o in orders_paid)),
                "gmvToday": revenue,
                "commissionEarned": revenue * 0.15,
            }

        # Calculate revenue from paid orders for global platform
        rev_result = await db.execute(
            select(Order).filter(Order.payment_status == "paid")
        )
        orders_paid = rev_result.scalars().all()
        revenue = sum(o.total for o in orders_paid)

        # Count orders
        orders_count_result = await db.execute(select(func.count(Order.id)))
        total_orders = orders_count_result.scalar() or 0

        # Count active stores (not deleted)
        stores_count_result = await db.execute(
            select(func.count(Store.id)).filter(Store.is_deleted == False)
        )
        active_stores = stores_count_result.scalar() or 0

        # Count active riders (status == 'online')
        riders_count_result = await db.execute(
            select(func.count(RiderProfile.id)).filter(RiderProfile.status == "online")
        )
        active_riders = riders_count_result.scalar() or 0

        # Count unique customers
        customer_ids_result = await db.execute(select(Order.customer_id).distinct())
        customers_count = len(customer_ids_result.scalars().all())

        return {
            "totalRevenue": revenue,
            "totalOrders": total_orders,
            "activeStoresCount": active_stores,
            "activeRidersCount": active_riders,
            "totalCustomersCount": customers_count,
            "gmvToday": revenue * 0.15,
            "commissionEarned": revenue * 0.05,
        }
