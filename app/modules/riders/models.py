from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, func, Index
from app.core.database import Base, Geography

class RiderProfile(Base):
    __tablename__ = "riders"

    id = Column(String(255), primary_key=True)
    vehicle_type = Column(String(50), nullable=False, index=True)  # 'motorcycle', 'bicycle', 'car'
    vehicle_plate = Column(String(50), nullable=True)
    status = Column(String(50), default="offline", index=True)     # 'offline', 'online', 'busy'
    rating = Column(Float, default=0.0)
    total_deliveries = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False, index=True)
    last_location = Column(Geography("Point"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Index GIS geography location for active rider queries
Index("idx_riders_location", RiderProfile.last_location, postgresql_using="gist")
