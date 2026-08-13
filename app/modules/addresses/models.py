from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.core.database import Base, Geography

class Address(Base):
    __tablename__ = "addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    label = Column(String(50), nullable=False)  # 'Home', 'Work', etc.
    address_text = Column(String(255), nullable=False)
    location = Column(Geography("Point"), nullable=False)  # Indexed coordinate
    delivery_instructions = Column(String, nullable=True)
    is_default = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
