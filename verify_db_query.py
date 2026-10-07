import asyncio
import app.main  # Loads all models and router modules
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.modules.products.models import Product

async def verify():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Product))
        products = res.scalars().all()
        print(f"VERIFIED: Successfully fetched {len(products)} products from database with new JSON columns!")

if __name__ == "__main__":
    asyncio.run(verify())
