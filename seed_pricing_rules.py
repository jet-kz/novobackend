import asyncio
from sqlalchemy.future import select
from app.core.database import engine, Base, AsyncSessionLocal
from app.modules.pricing.models import (
    CommissionRule,
    DeliveryPricingRule,
    ServiceFeeRule,
    PromotionCampaign,
    PromotionRedemption,
    PricingSnapshot
)
from app.modules.payments.models import LedgerEntry, Settlement


async def seed_pricing_system():
    print("Seeding Pricing Engine & Financial Rules...")
    # 0. Ensure tables exist in database
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created/verified.")

    async with AsyncSessionLocal() as session:
        # 1. Default Commission Rule (10%)
        res_c = await session.execute(
            select(CommissionRule).where(CommissionRule.merchant_id.is_(None))
        )
        if not res_c.scalar_one_or_none():
            session.add(CommissionRule(
                name="Default Platform Commission (10%)",
                rule_type="PERCENTAGE",
                value=10.0,
                flat_fee=0.0,
                min_order_amount=0.0,
                is_active=True
            ))
            print("Added default CommissionRule (10%)")

        # 2. Delivery Pricing Rule (Base ₦500, ₦150/km)
        res_d = await session.execute(select(DeliveryPricingRule).limit(1))
        if not res_d.scalar_one_or_none():
            session.add(DeliveryPricingRule(
                name="Standard Delivery Pricing",
                base_fee=500.0,
                per_km_fee=150.0,
                minimum_fee=500.0,
                maximum_fee=3000.0,
                surge_multiplier=1.0,
                zone_name="Lagos Mainland",
                is_active=True
            ))
            print("Added default DeliveryPricingRule")

        # 3. Service Fee Rule (2%)
        res_s = await session.execute(select(ServiceFeeRule).limit(1))
        if not res_s.scalar_one_or_none():
            session.add(ServiceFeeRule(
                name="Standard Platform Service Fee (2%)",
                fee_type="PERCENTAGE",
                value=2.0,
                minimum_fee=100.0,
                maximum_fee=1000.0,
                is_active=True
            ))
            print("Added default ServiceFeeRule (2%)")

        # 4. Promotions (WELCOME20, FIRSTORDER, WEEKEND_FREE)
        promos = [
            {
                "code": "WELCOME20",
                "name": "Welcome 20% Off",
                "description": "Get 20% off your first order over N5,000",
                "promo_type": "PERCENTAGE",
                "discount_value": 20.0,
                "min_order_amount": 5000.0,
                "max_discount_amount": 2000.0,
                "funding_source": "PLATFORM",
                "per_user_limit": 1
            },
            {
                "code": "FIRSTORDER",
                "name": "First Order N1,500 Off",
                "description": "N1,500 flat discount for new customers",
                "promo_type": "FIXED",
                "discount_value": 1500.0,
                "min_order_amount": 3000.0,
                "funding_source": "PLATFORM",
                "per_user_limit": 1
            },
            {
                "code": "FREE_DELIVERY",
                "name": "Free Delivery Campaign",
                "description": "Free delivery on orders over N10,000",
                "promo_type": "FREE_DELIVERY",
                "discount_value": 0.0,
                "min_order_amount": 10000.0,
                "funding_source": "PLATFORM",
                "per_user_limit": 3
            }
        ]

        for p in promos:
            res_p = await session.execute(
                select(PromotionCampaign).where(PromotionCampaign.code == p["code"])
            )
            if not res_p.scalar_one_or_none():
                session.add(PromotionCampaign(**p))
                print(f"Added PromotionCampaign ({p['code']})")

        await session.commit()
        print("✅ Pricing System Seeding Completed Successfully!")


if __name__ == "__main__":
    asyncio.run(seed_pricing_system())
