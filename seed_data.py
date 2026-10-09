import asyncio
import uuid
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.core.config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from app.integrations.supabase.client import supabase
from app.modules.users.models import UserProfile
from app.modules.merchants.models import Merchant
from app.modules.stores.models import Store
from app.modules.products.models import ProductCategory, Product
from app.modules.riders.models import RiderProfile


SEED_USERS = [
    {
        "email": "customer@novo.ng",
        "password": "Password123!",
        "full_name": "Jane Customer",
        "phone": "+2348011112222",
        "role": "customer"
    },
    {
        "email": "merchant@novo.ng",
        "password": "Password123!",
        "full_name": "Emeka Merchant",
        "phone": "+2348022223333",
        "role": "merchant_owner"
    },
    {
        "email": "rider@novo.ng",
        "password": "Password123!",
        "full_name": "Tunde Rider",
        "phone": "+2348033334444",
        "role": "rider"
    },
    {
        "email": "admin@novo.ng",
        "password": "Password123!",
        "full_name": "Novo Superadmin",
        "phone": "+2348044445555",
        "role": "superadmin"
    }
]


SEED_STORES = [
    {
        "name": "Novo Gourmet Kitchen",
        "slug": "novo-gourmet-kitchen",
        "store_type": "restaurant",
        "logo": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=300",
        "banner": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1000",
        "address": "14 Victoria Island, Lagos",
        "phone": "+2348022223333",
        "location": "SRID=4326;POINT(3.4219 6.4281)",
        "is_open": True,
        "is_verified": True,
        "categories": [
            {
                "name": "Main Dishes",
                "slug": "main-dishes",
                "products": [
                    {
                        "name": "Jollof Rice & Grilled Chicken",
                        "description": "Smoky Nigerian Jollof rice served with plantain and grilled chicken leg.",
                        "price": 4500.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1604329760661-e71dc83f8f26?w=500",
                        "rating": 4.9,
                        "preparation_time_minutes": 25,
                        "protein_options": ["Chicken", "Beef", "Fish", "Turkey"]
                    },
                    {
                        "name": "Peppered Beef & Fried Rice",
                        "description": "Special fried rice with diced vegetables and spicy peppered beef.",
                        "price": 5200.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1512058564366-18510be2db19?w=500",
                        "rating": 4.8,
                        "preparation_time_minutes": 30
                    }
                ]
            },
            {
                "name": "Soups & Swallows",
                "slug": "soups-swallows",
                "products": [
                    {
                        "name": "Egusi Soup with Pounded Yam",
                        "description": "Rich melon seed soup with assorted meat, stockfish, and smooth pounded yam.",
                        "price": 6000.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500",
                        "rating": 4.95,
                        "preparation_time_minutes": 35
                    }
                ]
            }
        ]
    },
    {
        "name": "FreshMart Supermarket",
        "slug": "freshmart-supermarket",
        "store_type": "supermarket",
        "logo": "https://images.unsplash.com/photo-1578916171728-46686eac8d58?w=300",
        "banner": "https://images.unsplash.com/photo-1542838132-92c53300491e?w=1000",
        "address": "45 Allen Avenue, Ikeja, Lagos",
        "phone": "+2348055556666",
        "location": "SRID=4326;POINT(3.3515 6.6018)",
        "is_open": True,
        "is_verified": True,
        "categories": [
            {
                "name": "Dairy & Eggs",
                "slug": "dairy-eggs",
                "products": [
                    {
                        "name": "Full Cream Fresh Milk 1L",
                        "description": "Pasteurized whole milk, 1 Liter pack.",
                        "price": 2200.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1563636619-e9143da7973b?w=500",
                        "rating": 4.7,
                        "preparation_time_minutes": 10
                    },
                    {
                        "name": "Farm Fresh Crate of Eggs (30pcs)",
                        "description": "Large Grade-A fresh farm eggs.",
                        "price": 4800.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1516467508483-a7212febe31a?w=500",
                        "rating": 4.85,
                        "preparation_time_minutes": 5
                    }
                ]
            }
        ]
    },
    {
        "name": "HealthPlus Pharmacy",
        "slug": "healthplus-pharmacy",
        "store_type": "pharmacy",
        "logo": "https://images.unsplash.com/photo-1586015555751-63bb77f4322a?w=300",
        "banner": "https://images.unsplash.com/photo-1576602976047-174e57a47881?w=1000",
        "address": "12 Admiralty Way, Lekki Phase 1, Lagos",
        "phone": "+2348077778888",
        "location": "SRID=4326;POINT(3.4705 6.4474)",
        "is_open": True,
        "is_verified": True,
        "categories": [
            {
                "name": "Vitamins & Supplements",
                "slug": "vitamins-supplements",
                "products": [
                    {
                        "name": "Vitamin C 1000mg Effervescent (20 Tabs)",
                        "description": "Immune system support dissolve tablets with Zinc.",
                        "price": 3500.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1584017911766-d451b3d0e843?w=500",
                        "rating": 4.9,
                        "preparation_time_minutes": 5
                    }
                ]
            }
        ]
    },
    {
        "name": "TechHub Electronics",
        "slug": "techhub-electronics",
        "store_type": "grocery",
        "logo": "https://images.unsplash.com/photo-1550009158-9ebf69173e03?w=300",
        "banner": "https://images.unsplash.com/photo-1526738549149-8e07eca6c147?w=1000",
        "address": "88 Commercial Avenue, Yaba, Lagos",
        "phone": "+2348099990000",
        "location": "SRID=4326;POINT(3.3792 6.5244)",
        "is_open": True,
        "is_verified": True,
        "categories": [
            {
                "name": "Audio & Accessories",
                "slug": "audio-accessories",
                "products": [
                    {
                        "name": "True Wireless Earbuds with ANC",
                        "description": "Active noise cancellation bluetooth earbuds with 24-hr battery case.",
                        "price": 28000.0,
                        "currency": "NGN",
                        "image": "https://images.unsplash.com/photo-1590658268037-6bf12165a8df?w=500",
                        "rating": 4.85,
                        "preparation_time_minutes": 10
                    }
                ]
            }
        ]
    }
]


async def seed():
    print("🌱 Starting database seed script...")

    DEFAULT_UUIDS = {
        "customer": "11111111-1111-4111-a111-111111111111",
        "merchant_owner": "22222222-2222-4222-a222-222222222222",
        "rider": "33333333-3333-4333-a333-333333333333",
        "superadmin": "44444444-4444-4444-a444-444444444444",
    }

    user_map = DEFAULT_UUIDS

    # 1. User Profiles & Supabase Auth Users
    for u in SEED_USERS:
        email = u["email"]
        password = u["password"]
        role = u["role"]
        name = u["full_name"]
        phone = u["phone"]
        uid = DEFAULT_UUIDS[role]

        try:
            # Create user in Supabase Auth using Service Role key
            new_u = supabase.auth.admin.create_user({
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {"role": role, "full_name": name}
            })
            if hasattr(new_u, "user") and new_u.user:
                uid = new_u.user.id
                print(f"  + Created Auth User: {email} (UUID: {uid})")
        except Exception as e:
            # If user already exists, retrieve ID
            try:
                list_res = supabase.auth.admin.list_users()
                users_list = list_res if isinstance(list_res, list) else getattr(list_res, "users", [])
                existing = next((x for x in users_list if getattr(x, "email", None) == email), None)
                if existing:
                    uid = existing.id
                    print(f"  ✓ Found existing Auth User: {email} (UUID: {uid})")
            except Exception:
                print(f"  ℹ Using default UUID for {email}: {uid}")

        user_map[role] = uid

        try:
            async with AsyncSessionLocal() as db:
                p_res = await db.execute(select(UserProfile).where(UserProfile.user_id == uid))
                p = p_res.scalar_one_or_none()
                if not p:
                    db.add(UserProfile(user_id=uid, full_name=name, phone=phone, is_active=True))
                    await db.commit()
                    print(f"  + UserProfile created for {email}")
        except Exception as e:
            print(f"  ⚠️ UserProfile {email}: {e}")

    merchant_user_id = user_map["merchant_owner"]

    # 2. Merchant Record
    merchant_id = uuid.uuid4()
    try:
        async with AsyncSessionLocal() as db:
            m_res = await db.execute(select(Merchant).where(Merchant.owner_id == merchant_user_id))
            m = m_res.scalar_one_or_none()
            if not m:
                m = Merchant(id=merchant_id, name="Novo Merchant Group", owner_id=merchant_user_id, status="active")
                db.add(m)
                await db.commit()
                print(f"  + Merchant record created")
            else:
                merchant_id = m.id
    except Exception as e:
        print(f"  ⚠️ Merchant record: {e}")

    # 3. Rider Profile
    rider_user_id = user_map["rider"]
    try:
        async with AsyncSessionLocal() as db:
            r_res = await db.execute(select(RiderProfile).where(RiderProfile.id == rider_user_id))
            r = r_res.scalar_one_or_none()
            if not r:
                r = RiderProfile(
                    id=rider_user_id,
                    vehicle_type="motorcycle",
                    vehicle_plate="LSD-458-XY",
                    status="online",
                    rating=4.9,
                    total_deliveries=48,
                    last_location="SRID=4326;POINT(3.3792 6.5244)"
                )
                db.add(r)
                await db.commit()
                print(f"  + Rider profile created")
    except Exception as e:
        print(f"  ⚠️ Rider profile: {e}")

    # 4. Stores & Products
    for s_data in SEED_STORES:
        try:
            async with AsyncSessionLocal() as db:
                s_res = await db.execute(select(Store).where(Store.slug == s_data["slug"]))
                store = s_res.scalar_one_or_none()
                if not store:
                    store = Store(
                        merchant_id=merchant_id,
                        name=s_data["name"],
                        slug=s_data["slug"],
                        store_type=s_data["store_type"],
                        logo=s_data["logo"],
                        banner=s_data["banner"],
                        address=s_data["address"],
                        phone=s_data["phone"],
                        location=s_data["location"],
                        is_open=s_data["is_open"],
                        is_verified=s_data["is_verified"]
                    )
                    db.add(store)
                    await db.commit()
                    await db.refresh(store)
                    print(f"  + Store created: {store.name}")

                for cat_data in s_data.get("categories", []):
                    c_res = await db.execute(select(ProductCategory).where(
                        ProductCategory.store_id == store.id,
                        ProductCategory.slug == cat_data["slug"]
                    ))
                    cat = c_res.scalar_one_or_none()
                    if not cat:
                        cat = ProductCategory(
                            store_id=store.id,
                            name=cat_data["name"],
                            slug=cat_data["slug"]
                        )
                        db.add(cat)
                        await db.commit()
                        await db.refresh(cat)

                    for p_data in cat_data.get("products", []):
                        p_res = await db.execute(select(Product).where(
                            Product.store_id == store.id,
                            Product.name == p_data["name"]
                        ))
                        prod = p_res.scalar_one_or_none()
                        if not prod:
                            prod = Product(
                                store_id=store.id,
                                category_id=cat.id,
                                name=p_data["name"],
                                description=p_data.get("description"),
                                price=p_data["price"],
                                currency=p_data["currency"],
                                image=p_data.get("image"),
                                in_stock=True,
                                rating=p_data.get("rating", 4.5),
                                preparation_time_minutes=p_data.get("preparation_time_minutes", 15),
                                protein_options=p_data.get("protein_options", [])
                            )
                            db.add(prod)
                            await db.commit()
                            print(f"    - Product: {prod.name}")
        except Exception as e:
            print(f"  ⚠️ Store {s_data['name']}: {e}")

    print("\n✅ Seed complete! All 4 user roles and 4 stores are populated.")


if __name__ == "__main__":
    asyncio.run(seed())
