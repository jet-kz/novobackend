from sqlalchemy import Column, String, DateTime, func, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor = Column(String(255), nullable=False)  # User ID or service name
    action = Column(String(100), nullable=False)  # e.g., 'wallet:payout'
    entity_type = Column(String(50), nullable=False)  # e.g., 'wallets'
    entity_id = Column(String(255), nullable=False)
    action_metadata = Column(JSONB, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
