import uuid

from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class Notification(Base):
    """In-app message for a user (e.g. admin -> rider). Usually also sent by email."""
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(150), nullable=False)
    body = Column(Text, nullable=False)
    kind = Column(String(30), nullable=False, default="message")  # message | approval | system
    sender_id = Column(String(255), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PushSubscription(Base):
    """A browser/phone that agreed to receive push notifications."""
    __tablename__ = "push_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False, unique=True)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=True, index=True)  # signed-in user
    guest_order_id = Column(String(50), nullable=True, index=True)  # guest following one order
    open_url = Column(String(500), nullable=True)  # where a guest's notification should open (has their token)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
