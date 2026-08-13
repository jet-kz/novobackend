from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.modules.orders.models import Order
from app.modules.stores.models import Store
from app.modules.riders.models import RiderProfile

class AnalyticsService:
    @staticmethod
    async def get_analytics(db: AsyncSession):
        # Calculate revenue from paid orders
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
