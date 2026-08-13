from sqlalchemy import Column, String, Boolean, Float, ForeignKey, DateTime, func, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base

class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(120), nullable=False)
    is_deleted = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    products = relationship("Product", back_populates="category")

    __table_args__ = (
        UniqueConstraint("store_id", "slug", name="uq_product_categories_store_slug"),
    )

class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(120), nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)  # Associated currency
    image = Column(String(255), nullable=True)
    in_stock = Column(Boolean, default=True)
    is_deleted = Column(Boolean, default=False, index=True)
    rating = Column(Float, default=0.0)
    preparation_time_minutes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    store = relationship("Store", back_populates="products")
    category = relationship("ProductCategory", back_populates="products")
    options = relationship("ProductOption", back_populates="product", cascade="all, delete-orphan")

class ProductOption(Base):
    __tablename__ = "product_options"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    price = Column(Float, default=0.0)
    currency = Column(String(10), nullable=False)

    product = relationship("Product", back_populates="options")
