import math
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.pricing.models import (
    CommissionRule,
    DeliveryPricingRule,
    ServiceFeeRule,
    PromotionCampaign,
    PromotionRedemption,
    PricingSnapshot
)
from app.modules.pricing.schemas import (
    PricingCalculateRequest,
    PricingBreakdownResponse,
    ValidatePromoRequest,
    ValidatePromoResponse
)


class PricingEngine:
    @staticmethod
    async def get_delivery_fee(
        session: AsyncSession,
        distance_km: float = 3.0,
        zone_name: Optional[str] = "Lagos Mainland"
    ) -> Dict[str, Any]:
        res = await session.execute(
            select(DeliveryPricingRule).where(
                DeliveryPricingRule.is_active == True
            ).limit(1)
        )
        rule = res.scalar_one_or_none()

        base_fee = rule.base_fee if rule else 500.0
        per_km_fee = rule.per_km_fee if rule else 150.0
        min_fee = rule.minimum_fee if rule else 500.0
        max_fee = rule.maximum_fee if rule else 3000.0
        surge = rule.surge_multiplier if rule else 1.0

        calculated = base_fee + (distance_km * per_km_fee)
        clamped = max(min_fee, min(calculated, max_fee))
        final_fee = round(clamped * surge, 2)

        return {
            "fee": final_fee,
            "base_fee": base_fee,
            "per_km_fee": per_km_fee,
            "surge_multiplier": surge,
            "rule_name": rule.name if rule else "Default Rule"
        }

    @staticmethod
    async def get_service_fee(
        session: AsyncSession,
        subtotal: float
    ) -> Dict[str, Any]:
        res = await session.execute(
            select(ServiceFeeRule).where(
                ServiceFeeRule.is_active == True
            ).limit(1)
        )
        rule = res.scalar_one_or_none()

        fee_type = rule.fee_type if rule else "PERCENTAGE"
        val = rule.value if rule else 2.0
        min_fee = rule.minimum_fee if rule else 100.0
        max_fee = rule.maximum_fee if rule else 1000.0

        if fee_type == "FLAT":
            raw_fee = val
        else:
            raw_fee = subtotal * (val / 100.0)

        final_fee = round(max(min_fee, min(raw_fee, max_fee)), 2)

        return {
            "fee": final_fee,
            "rule_name": rule.name if rule else "Default Service Fee"
        }

    @staticmethod
    async def get_commission(
        session: AsyncSession,
        subtotal: float,
        merchant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        rule = None
        if merchant_id:
            res_m = await session.execute(
                select(CommissionRule).where(
                    (CommissionRule.merchant_id == merchant_id) & (CommissionRule.is_active == True)
                ).limit(1)
            )
            rule = res_m.scalar_one_or_none()

        if not rule:
            res_def = await session.execute(
                select(CommissionRule).where(
                    (CommissionRule.merchant_id.is_(None)) & (CommissionRule.is_active == True)
                ).limit(1)
            )
            rule = res_def.scalar_one_or_none()

        rate = rule.value if rule else 10.0 # Default 10%
        flat = rule.flat_fee if rule else 0.0

        commission_amount = round((subtotal * (rate / 100.0)) + flat, 2)

        return {
            "rate": rate,
            "flat_fee": flat,
            "commission_amount": commission_amount,
            "rule_name": rule.name if rule else "Default 10% Commission"
        }

    @staticmethod
    async def evaluate_promotion(
        session: AsyncSession,
        code: str,
        subtotal: float,
        delivery_fee: float,
        merchant_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if not code:
            return {"valid": False, "discount": 0.0, "message": "No code provided"}

        res = await session.execute(
            select(PromotionCampaign).where(
                (PromotionCampaign.code == code.upper().strip()) & (PromotionCampaign.is_active == True)
            ).limit(1)
        )
        campaign = res.scalar_one_or_none()

        if not campaign:
            return {"valid": False, "discount": 0.0, "message": f"Promo code '{code}' is invalid or expired"}

        now = datetime.utcnow()
        if campaign.ends_at and campaign.ends_at < now:
            return {"valid": False, "discount": 0.0, "message": "Promo code has expired"}

        if subtotal < campaign.min_order_amount:
            return {
                "valid": False,
                "discount": 0.0,
                "message": f"Minimum order of N{campaign.min_order_amount:,.2f} required for promo code"
            }

        if campaign.usage_limit and campaign.current_redemptions >= campaign.usage_limit:
            return {"valid": False, "discount": 0.0, "message": "Promo code global usage limit reached"}

        if user_id:
            res_u = await session.execute(
                select(PromotionRedemption).where(
                    (PromotionRedemption.campaign_id == campaign.id) & (PromotionRedemption.user_id == user_id)
                )
            )
            user_redemptions = len(res_u.scalars().all())
            if user_redemptions >= campaign.per_user_limit:
                return {"valid": False, "discount": 0.0, "message": "You have reached your limit for this promo code"}

        # Calculate Discount
        discount = 0.0
        if campaign.promo_type == "FREE_DELIVERY":
            discount = delivery_fee
        elif campaign.promo_type == "PERCENTAGE":
            discount = subtotal * (campaign.discount_value / 100.0)
        elif campaign.promo_type == "FIXED":
            discount = campaign.discount_value

        if campaign.max_discount_amount and discount > campaign.max_discount_amount:
            discount = campaign.max_discount_amount

        discount = round(min(discount, subtotal + delivery_fee), 2)

        return {
            "valid": True,
            "campaign_id": campaign.id,
            "code": campaign.code,
            "discount": discount,
            "promo_type": campaign.promo_type,
            "funding_source": campaign.funding_source,
            "merchant_funding_share": campaign.merchant_funding_share,
            "message": f"Promo code {campaign.code} applied (-N{discount:,.2f})"
        }

    @staticmethod
    async def calculate_checkout_pricing(
        session: AsyncSession,
        req: PricingCalculateRequest
    ) -> PricingBreakdownResponse:
        subtotal = round(req.subtotal, 2)

        # 1. Delivery Fee
        del_res = await PricingEngine.get_delivery_fee(session, req.distance_km, req.zone_name)
        delivery_fee = del_res["fee"]

        # 2. Service Fee
        serv_res = await PricingEngine.get_service_fee(session, subtotal)
        service_fee = serv_res["fee"]

        # 3. Commission
        comm_res = await PricingEngine.get_commission(session, subtotal, req.merchant_id)
        commission_rate = comm_res["rate"]
        commission_amount = comm_res["commission_amount"]

        # 4. Promotion / Discount
        discount = 0.0
        applied_code = None
        funding_source = "PLATFORM"
        merchant_promo_deduction = 0.0

        if req.promo_code:
            promo_res = await PricingEngine.evaluate_promotion(
                session, req.promo_code, subtotal, delivery_fee, req.merchant_id, req.user_id
            )
            if promo_res["valid"]:
                discount = promo_res["discount"]
                applied_code = promo_res["code"]
                funding_source = promo_res["funding_source"]

                if funding_source == "RESTAURANT":
                    merchant_promo_deduction = discount
                elif funding_source == "SHARED":
                    share = promo_res.get("merchant_funding_share", 0.5)
                    merchant_promo_deduction = discount * share

        # 5. Order Total
        total = round(max(0.0, subtotal + delivery_fee + service_fee - discount), 2)

        # 6. Earnings Breakdown
        restaurant_net = round(max(0.0, subtotal - commission_amount - merchant_promo_deduction), 2)
        rider_earning = round(delivery_fee * 0.85, 2) # 85% of delivery fee to rider
        platform_revenue = round(total - restaurant_net - rider_earning, 2)

        return PricingBreakdownResponse(
            subtotal=subtotal,
            delivery_fee=delivery_fee,
            service_fee=service_fee,
            discount=discount,
            total=total,
            commission_rate=commission_rate,
            commission_amount=commission_amount,
            restaurant_net_earning=restaurant_net,
            rider_earning=rider_earning,
            platform_revenue=platform_revenue,
            applied_promo_code=applied_code,
            promo_funding_source=funding_source,
            details={
                "delivery_rule": del_res["rule_name"],
                "service_rule": serv_res["rule_name"],
                "commission_rule": comm_res["rule_name"]
            }
        )

    @staticmethod
    async def create_pricing_snapshot(
        session: AsyncSession,
        order_id: str,
        breakdown: PricingBreakdownResponse
    ) -> PricingSnapshot:
        snapshot = PricingSnapshot(
            order_id=order_id,
            subtotal=breakdown.subtotal,
            delivery_fee=breakdown.delivery_fee,
            service_fee=breakdown.service_fee,
            discount=breakdown.discount,
            total=breakdown.total,
            commission_rate=breakdown.commission_rate,
            commission_amount=breakdown.commission_amount,
            restaurant_net_earning=breakdown.restaurant_net_earning,
            rider_earning=breakdown.rider_earning,
            platform_revenue=breakdown.platform_revenue,
            applied_promo_code=breakdown.applied_promo_code,
            funding_source=breakdown.promo_funding_source,
            details_json=breakdown.details
        )
        session.add(snapshot)
        await session.commit()
        return snapshot
