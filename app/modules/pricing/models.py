import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class CommissionRule(Base):
    __tablename__ = "commission_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, default="Default Platform Commission")
    rule_type = Column(String, nullable=False, default="PERCENTAGE") # PERCENTAGE, FLAT, PERCENTAGE_PLUS_FLAT
    value = Column(Float, nullable=False, default=10.0) # e.g. 10.0 for 10%
    flat_fee = Column(Float, nullable=False, default=0.0) # e.g. 100 for N100
    merchant_id = Column(String, nullable=True) # None = default global, or specific merchant_id
    min_order_amount = Column(Float, nullable=False, default=0.0)
    max_order_amount = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeliveryPricingRule(Base):
    __tablename__ = "delivery_pricing_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, default="Standard Delivery Pricing")
    base_fee = Column(Float, nullable=False, default=500.0) # Base N500
    per_km_fee = Column(Float, nullable=False, default=150.0) # N150 per KM
    minimum_fee = Column(Float, nullable=False, default=500.0)
    maximum_fee = Column(Float, nullable=False, default=3000.0)
    surge_multiplier = Column(Float, nullable=False, default=1.0)
    zone_name = Column(String, nullable=False, default="Lagos Mainland")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ServiceFeeRule(Base):
    __tablename__ = "service_fee_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, default="Standard Platform Service Fee")
    fee_type = Column(String, nullable=False, default="PERCENTAGE") # PERCENTAGE, FLAT
    value = Column(Float, nullable=False, default=2.0) # 2%
    minimum_fee = Column(Float, nullable=False, default=100.0)
    maximum_fee = Column(Float, nullable=False, default=1000.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PromotionCampaign(Base):
    __tablename__ = "promotion_campaigns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String, unique=True, index=True, nullable=False) # e.g. WELCOME20, FIRSTORDER
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    promo_type = Column(String, nullable=False, default="PERCENTAGE") # PERCENTAGE, FIXED, FREE_DELIVERY
    discount_value = Column(Float, nullable=False, default=0.0)
    min_order_amount = Column(Float, nullable=False, default=0.0)
    max_discount_amount = Column(Float, nullable=True)
    funding_source = Column(String, nullable=False, default="PLATFORM") # PLATFORM, RESTAURANT, SHARED
    merchant_funding_share = Column(Float, nullable=False, default=0.0) # percentage or fraction funded by merchant if SHARED
    applicable_merchant_id = Column(String, nullable=True) # None = all merchants, or specific merchant_id
    usage_limit = Column(Integer, nullable=True) # Total global redemptions allowed
    per_user_limit = Column(Integer, nullable=False, default=1)
    current_redemptions = Column(Integer, nullable=False, default=0)
    starts_at = Column(DateTime, default=datetime.utcnow)
    ends_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PromotionRedemption(Base):
    __tablename__ = "promotion_redemptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = Column(String, ForeignKey("promotion_campaigns.id"), nullable=False)
    user_id = Column(String, nullable=False)
    order_id = Column(String, nullable=True)
    discount_applied = Column(Float, nullable=False, default=0.0)
    redeemed_at = Column(DateTime, default=datetime.utcnow)


class PricingSnapshot(Base):
    __tablename__ = "pricing_snapshots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String, unique=True, index=True, nullable=False)
    subtotal = Column(Float, nullable=False)
    delivery_fee = Column(Float, nullable=False)
    service_fee = Column(Float, nullable=False)
    discount = Column(Float, nullable=False, default=0.0)
    total = Column(Float, nullable=False)
    commission_rate = Column(Float, nullable=False)
    commission_amount = Column(Float, nullable=False)
    restaurant_net_earning = Column(Float, nullable=False)
    rider_earning = Column(Float, nullable=False)
    platform_revenue = Column(Float, nullable=False)
    applied_promo_code = Column(String, nullable=True)
    funding_source = Column(String, nullable=False, default="PLATFORM")
    details_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
