from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class PricingCalculateRequest(BaseModel):
    subtotal: float = Field(..., gt=0, description="Cart subtotal amount in NGN")
    merchant_id: Optional[str] = None
    user_id: Optional[str] = None
    promo_code: Optional[str] = None
    distance_km: float = Field(default=3.0, ge=0.0)
    zone_name: Optional[str] = "Lagos Mainland"


class PricingBreakdownResponse(BaseModel):
    subtotal: float
    delivery_fee: float
    service_fee: float
    discount: float
    total: float
    commission_rate: float
    commission_amount: float
    restaurant_net_earning: float
    rider_earning: float
    platform_revenue: float
    applied_promo_code: Optional[str] = None
    promo_funding_source: str = "PLATFORM"
    details: Dict[str, Any] = {}


class ValidatePromoRequest(BaseModel):
    code: str
    subtotal: float
    merchant_id: Optional[str] = None
    user_id: Optional[str] = None


class ValidatePromoResponse(BaseModel):
    valid: bool
    code: str
    discount_amount: float
    promo_type: str
    funding_source: str
    message: str


class CommissionRuleSchema(BaseModel):
    id: Optional[str] = None
    name: str
    rule_type: str = "PERCENTAGE"
    value: float = 10.0
    flat_fee: float = 0.0
    merchant_id: Optional[str] = None
    min_order_amount: float = 0.0
    max_order_amount: Optional[float] = None
    is_active: bool = True


class DeliveryPricingRuleSchema(BaseModel):
    id: Optional[str] = None
    name: str
    base_fee: float = 500.0
    per_km_fee: float = 150.0
    minimum_fee: float = 500.0
    maximum_fee: float = 3000.0
    surge_multiplier: float = 1.0
    zone_name: str = "Lagos Mainland"
    is_active: bool = True


class ServiceFeeRuleSchema(BaseModel):
    id: Optional[str] = None
    name: str
    fee_type: str = "PERCENTAGE"
    value: float = 2.0
    minimum_fee: float = 100.0
    maximum_fee: float = 1000.0
    is_active: bool = True


class CreatePromotionCampaignSchema(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    promo_type: str = "PERCENTAGE" # PERCENTAGE, FIXED, FREE_DELIVERY
    discount_value: float = 0.0
    min_order_amount: float = 0.0
    max_discount_amount: Optional[float] = None
    funding_source: str = "PLATFORM" # PLATFORM, RESTAURANT, SHARED
    merchant_funding_share: float = 0.0
    applicable_merchant_id: Optional[str] = None
    usage_limit: Optional[int] = None
    per_user_limit: int = 1
    ends_at: Optional[datetime] = None
    is_active: bool = True
