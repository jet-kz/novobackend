import asyncio
from app.modules.orders.service import OrderService
from app.core.database import AsyncSessionLocal

async def test_create_order():
    async with AsyncSessionLocal() as db:
        order_data = {
            "items": [{"name": "Jollof Rice", "quantity": 1, "price": 3500}],
            "subtotal": 3500,
            "total": 3800,
            "customer_name": "Test Customer",
            "delivery_address": "123 Lekki Phase 1",
        }
        order = await OrderService.create_order(db, "00000000-0000-0000-0000-000000000001", order_data)
        print(f"SUCCESS: Created Order #{order.id} with status {order.status} and total ₦{order.total}!")

if __name__ == "__main__":
    import app.main
    asyncio.run(test_create_order())
