from sqlalchemy import Column, String, Boolean, DateTime, func
from app.core.database import Base


class UserProfile(Base):
    """
    Application-level user profile table.
    Extends the Supabase Auth user (auth.users) with business profile data.
    The `user_id` is the Supabase Auth UUID (sub claim from JWT).
    """
    __tablename__ = "user_profiles"

    user_id = Column(String(255), primary_key=True)  # Supabase Auth UUID
    full_name = Column(String(120), nullable=True)
    phone = Column(String(50), nullable=True)
    avatar_url = Column(String(500), nullable=True)   # URL returned by Supabase Storage
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
