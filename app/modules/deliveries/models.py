from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func, Integer, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base, Geography

class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id = Column(String(255), ForeignKey("riders.id", ondelete="SET NULL"), nullable=True, index=True)
    pickup_location = Column(Geography("Point"), nullable=False)
    dropoff_location = Column(Geography("Point"), nullable=False)
    status = Column(String(50), nullable=False, default="pending_assignment", index=True)  # 'pending_assignment', 'assigned', 'picked_up', 'delivered', 'failed'
    fee = Column(Float, nullable=False, default=0.0)
    rider_earnings = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    picked_up_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignments = relationship("DeliveryAssignment", back_populates="delivery", cascade="all, delete-orphan")

class DeliveryAssignment(Base):
    __tablename__ = "delivery_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    delivery_id = Column(UUID(as_uuid=True), ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id = Column(String(255), ForeignKey("riders.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="offered")  # 'offered', 'accepted', 'rejected', 'expired'
    offered_at = Column(DateTime(timezone=True), server_default=func.now())
    responded_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    delivery = relationship("Delivery", back_populates="assignments")

class RiderLocationHistory(Base):
    __tablename__ = "rider_location_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rider_id = Column(String(255), ForeignKey("riders.id", ondelete="CASCADE"), nullable=False, index=True)
    location = Column(Geography("Point"), nullable=False)
    captured_at = Column(DateTime(timezone=True), server_default=func.now())

# Set up spatial GiST indexes for geolocation columns
Index("idx_deliveries_pickup", Delivery.pickup_location, postgresql_using="gist")
Index("idx_deliveries_dropoff", Delivery.dropoff_location, postgresql_using="gist")
Index("idx_rider_location_history_geom", RiderLocationHistory.location, postgresql_using="gist")
