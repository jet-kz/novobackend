from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.core.database import Base

class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    holder_id = Column(String(255), nullable=False, index=True) # customer/rider/merchant user identifier
    currency = Column(String(10), nullable=False)
    balance = Column(Float, default=0.00)

    __table_args__ = (
        UniqueConstraint("holder_id", "currency", name="uq_wallets_holder_currency"),
    )

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wallet_id = Column(UUID(as_uuid=True), ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    direction = Column(String(10), nullable=False)     # 'credit', 'debit'
    txn_type = Column(String(50), nullable=False)      # 'payment', 'payout', 'commission', 'refund', 'rider_earning'
    reference = Column(String(255), nullable=True)     # links to Order, Payout ID, etc.
    created_at = Column(DateTime(timezone=True), server_default=func.now())
