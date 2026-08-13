import asyncio
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.modules.auth.models import Role, Permission, UserRole
from app.modules.merchants.models import Merchant
from app.modules.stores.models import Store
from app.modules.products.models import ProductCategory, Product
from app.modules.riders.models import RiderProfile

async def seed_data():
    async with AsyncSessionLocal() as session:
        # Seed core roles
        super_admin_role_id = "role_" + str(uuid.uuid4())
        customer_role_id = "role_" + str(uuid.uuid4())
        merchant_role_id = "role_" + str(uuid.uuid4())
        rider_role_id = "role_" + str(uuid.uuid4())

        roles = [
            Role(id=super_admin_role_id, name="super_admin"),
            Role(id=customer_role_id, name="customer"),
            Role(id=merchant_role_id, name="merchant_owner"),
            Role(id=rider_role_id, name="rider"),
        ]
        
        session.add_all(roles)
        await session.flush()
        print("Inserted Base Roles")

        # Create Merchant Example
        owner_id = "auth_usr_" + str(uuid.uuid4()) # Mocks a supabase auth.user id
        merchant_id = uuid.uuid4()
        merchant = Merchant(
            id=merchant_id,
            name="KFC Global Group",
            owner_id=owner_id,
            status="active"
        )
        session.add(merchant)
        await session.flush()
        print(f"Inserted dummy merchant: {merchant.name}")

        # Create Store for Merchant
        store_id = uuid.uuid4()
        store = Store(
            id=store_id,
            merchant_id=merchant_id,
            name="KFC Lekki Phase 1",
            slug="kfc-lekki-1",
            store_type="restaurant",
            location=f"POINT(3.468205 6.444158)", # WKT For Postgis
            is_open=True,
            is_verified=True
        )
        session.add(store)
        await session.flush()
        print(f"Inserted store: {store.name}")

        # Create Categories
        burger_cat_id = uuid.uuid4()
        categories = [
            ProductCategory(id=burger_cat_id, store_id=store_id, name="Burgers & Meals", slug="burgers-and-meals"),
            ProductCategory(id=uuid.uuid4(), store_id=store_id, name="Beverages", slug="beverages"),
        ]
        session.add_all(categories)
        await session.flush()
        print("Inserted categories")

        # Create Products
        prod_id = uuid.uuid4()
        product = Product(
            id=prod_id,
            store_id=store_id,
            category_id=burger_cat_id,
            name="Zinger Burger Meal",
            description="Spicy deep fried chicken breast served with fries and a drink",
            price=4500.00,
            currency="NGN",
            in_stock=True,
            preparation_time_minutes=15
        )
        session.add(product)
        await session.flush()
        print("Inserted product: Zinger Burger Meal")

        # Create Rider Profile
        rider = RiderProfile(
            id="auth_rider_" + str(uuid.uuid4()),
            vehicle_type="motorcycle",
            vehicle_plate="LSR-123XD",
            status="online",
            rating=4.9,
            total_deliveries=0,
            last_location=f"POINT(3.47 6.45)" 
        )
        session.add(rider)

        await session.commit()
        print("Seeding completed successfully!")

if __name__ == "__main__":
    asyncio.run(seed_data())
