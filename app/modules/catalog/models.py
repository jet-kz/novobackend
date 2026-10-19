import uuid

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class PlatformCategory(Base):
    """Homepage categories (Food, Groceries, ...). `slug` matches stores.store_type."""
    __tablename__ = "platform_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug = Column(String(50), nullable=False, unique=True)
    name = Column(String(80), nullable=False)
    icon = Column(String(255), nullable=True)  # emoji or image URL
    description = Column(String(255), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HomeCollection(Base):
    """Featured strip on the homepage, e.g. 'Late night grills' -> restaurants."""
    __tablename__ = "home_collections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(100), nullable=False)
    subtitle = Column(String(200), nullable=True)
    badge = Column(String(40), nullable=True)
    image = Column(String(500), nullable=True)
    target_category = Column(String(50), nullable=False, default="all")  # platform category slug or 'all'
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PromoBanner(Base):
    """Rotating ad/promo banner on the homepage. Admins upload the artwork and schedule it."""
    __tablename__ = "promo_banners"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(120), nullable=True)
    subtitle = Column(String(240), nullable=True)
    image = Column(String(500), nullable=False)
    cta_label = Column(String(40), nullable=True)
    link_url = Column(String(500), nullable=True)  # "/shop?store=..." or https://...
    placement = Column(String(30), nullable=False, default="home", index=True)
    # Off when the artwork already carries its own text, so we don't print a title over it.
    show_text = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
