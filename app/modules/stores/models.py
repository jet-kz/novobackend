from sqlalchemy import Column, String, Boolean, Float, ForeignKey, DateTime, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base, Geography

class Store(Base):
    __tablename__ = "stores"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(120), nullable=False, unique=True)
    store_type = Column(String(50), nullable=False, index=True)  # 'restaurant', 'supermarket', 'pharmacy', 'grocery', etc.
    logo = Column(String(255), nullable=True)
    banner = Column(String(255), nullable=True)
    address = Column(String(255), nullable=True)
    location = Column(Geography("Point"), nullable=False)         # Geopoint coordinate
    is_open = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False, index=True)
    settings = Column(JSONB, nullable=True)                      # Flexible tax/hours settings
    phone = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="store", cascade="all, delete-orphan")
    pricing_rules = relationship("PricingRule", back_populates="store", cascade="all, delete-orphan")

class PricingRule(Base):
    __tablename__ = "pricing_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True)
    rule_type = Column(String(50), nullable=False)
    parameters = Column(JSONB, nullable=False)
    currency = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True)

    store = relationship("Store", back_populates="pricing_rules")

Index("idx_stores_location", Store.location, postgresql_using="gist")
