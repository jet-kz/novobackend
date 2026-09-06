from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import get_db
from app.modules.pricing.schemas import (
    PricingCalculateRequest,
    PricingBreakdownResponse,
    ValidatePromoRequest,
    ValidatePromoResponse,
    CommissionRuleSchema,
    DeliveryPricingRuleSchema,
    ServiceFeeRuleSchema,
    CreatePromotionCampaignSchema
)
from app.modules.pricing.service import PricingEngine
from app.modules.pricing.models import (
    CommissionRule,
    DeliveryPricingRule,
    ServiceFeeRule,
    PromotionCampaign
)

router = APIRouter()


@router.post("/calculate", response_model=PricingBreakdownResponse)
async def calculate_pricing(
    req: PricingCalculateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Calculates dynamic order pricing breakdown (subtotal, delivery fee, service fee, promotion discount, commission, restaurant net, rider share).
    """
    try:
        return await PricingEngine.calculate_checkout_pricing(db, req)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to calculate pricing: {str(e)}"
        )


@router.post("/validate-promo", response_model=ValidatePromoResponse)
async def validate_promo_code(
    req: ValidatePromoRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Validates a promo code for eligibility and spend bounds.
    """
    res = await PricingEngine.evaluate_promotion(
        db, req.code, req.subtotal, 500.0, req.merchant_id, req.user_id
    )
    if not res["valid"]:
        return ValidatePromoResponse(
            valid=False,
            code=req.code,
            discount_amount=0.0,
            promo_type="NONE",
            funding_source="PLATFORM",
            message=res["message"]
        )

    return ValidatePromoResponse(
        valid=True,
        code=res["code"],
        discount_amount=res["discount"],
        promo_type=res["promo_type"],
        funding_source=res["funding_source"],
        message=res["message"]
    )


# --- ADMIN CONFIGURATION ENDPOINTS ---

@router.get("/rules/commission")
async def get_commission_rules(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(CommissionRule))
    return res.scalars().all()


@router.post("/rules/commission")
async def save_commission_rule(
    schema: CommissionRuleSchema,
    db: AsyncSession = Depends(get_db)
):
    if schema.id:
        res = await db.execute(select(CommissionRule).where(CommissionRule.id == schema.id))
        rule = res.scalar_one_or_none()
        if rule:
            rule.name = schema.name
            rule.value = schema.value
            rule.flat_fee = schema.flat_fee
            rule.merchant_id = schema.merchant_id
            rule.min_order_amount = schema.min_order_amount
            rule.is_active = schema.is_active
            await db.commit()
            return rule

    rule = CommissionRule(
        name=schema.name,
        rule_type=schema.rule_type,
        value=schema.value,
        flat_fee=schema.flat_fee,
        merchant_id=schema.merchant_id,
        min_order_amount=schema.min_order_amount,
        is_active=schema.is_active
    )
    db.add(rule)
    await db.commit()
    return rule


@router.get("/rules/delivery")
async def get_delivery_rules(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(DeliveryPricingRule))
    return res.scalars().all()


@router.post("/rules/delivery")
async def save_delivery_rule(
    schema: DeliveryPricingRuleSchema,
    db: AsyncSession = Depends(get_db)
):
    if schema.id:
        res = await db.execute(select(DeliveryPricingRule).where(DeliveryPricingRule.id == schema.id))
        rule = res.scalar_one_or_none()
        if rule:
            rule.base_fee = schema.base_fee
            rule.per_km_fee = schema.per_km_fee
            rule.minimum_fee = schema.minimum_fee
            rule.maximum_fee = schema.maximum_fee
            rule.surge_multiplier = schema.surge_multiplier
            rule.is_active = schema.is_active
            await db.commit()
            return rule

    rule = DeliveryPricingRule(
        name=schema.name,
        base_fee=schema.base_fee,
        per_km_fee=schema.per_km_fee,
        minimum_fee=schema.minimum_fee,
        maximum_fee=schema.maximum_fee,
        surge_multiplier=schema.surge_multiplier,
        is_active=schema.is_active
    )
    db.add(rule)
    await db.commit()
    return rule


@router.get("/rules/service-fee")
async def get_service_fee_rules(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ServiceFeeRule))
    return res.scalars().all()


@router.post("/rules/service-fee")
async def save_service_fee_rule(
    schema: ServiceFeeRuleSchema,
    db: AsyncSession = Depends(get_db)
):
    rule = ServiceFeeRule(
        name=schema.name,
        fee_type=schema.fee_type,
        value=schema.value,
        minimum_fee=schema.minimum_fee,
        maximum_fee=schema.maximum_fee,
        is_active=schema.is_active
    )
    db.add(rule)
    await db.commit()
    return rule


@router.get("/promotions")
async def get_promotions(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(PromotionCampaign))
    return res.scalars().all()


@router.post("/promotions")
async def create_promotion(
    schema: CreatePromotionCampaignSchema,
    db: AsyncSession = Depends(get_db)
):
    campaign = PromotionCampaign(
        code=schema.code.upper().strip(),
        name=schema.name,
        description=schema.description,
        promo_type=schema.promo_type,
        discount_value=schema.discount_value,
        min_order_amount=schema.min_order_amount,
        max_discount_amount=schema.max_discount_amount,
        funding_source=schema.funding_source,
        merchant_funding_share=schema.merchant_funding_share,
        applicable_merchant_id=schema.applicable_merchant_id,
        usage_limit=schema.usage_limit,
        per_user_limit=schema.per_user_limit,
        ends_at=schema.ends_at,
        is_active=schema.is_active
    )
    db.add(campaign)
    await db.commit()
    return campaign
