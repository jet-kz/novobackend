from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func, Integer, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(50), primary_key=True)
    customer_id = Column(String(255), nullable=False, index=True)
    customer_name = Column(String(120), nullable=False)
    customer_phone = Column(String(50), nullable=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    address_id = Column(UUID(as_uuid=True), ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True, index=True)
    subtotal = Column(Float, nullable=False)
    delivery_fee = Column(Float, default=0.0)
    service_fee = Column(Float, default=0.0)
    tax = Column(Float, default=0.0)
    tip = Column(Float, default=0.0)
    total = Column(Float, nullable=False)
    payment_status = Column(String(50), default="unpaid")
    status = Column(String(50), nullable=False, default="CART", index=True)
    payment_method = Column(String(50), default="card")
    currency = Column(String(10), nullable=False)
    delivery_longitude = Column(Float, nullable=False)
    delivery_latitude = Column(Float, nullable=False)
    delivery_address = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(120), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    addons = Column(JSONB, nullable=True)

    order = relationship("Order", back_populates="items")

class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    changed_by_id = Column(String(255), nullable=False)
    cancellation_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="history")
