from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from app.core.database import Base

class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # 'pending', 'paid', 'failed', 'refunded'
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    transactions = relationship("PaymentTransaction", back_populates="payment", cascade="all, delete-orphan")
    refunds = relationship("Refund", back_populates="payment", cascade="all, delete-orphan")

class PaymentTransaction(Base):
    __tablename__ = "payment_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    txn_type = Column(String(50), nullable=False)  # 'charge', 'refund'
    provider = Column(String(50), nullable=False)  # 'paystack', 'stripe', etc.
    provider_reference = Column(String(255), nullable=False, unique=True, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    status = Column(String(50), nullable=False)
    provider_metadata = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payment = relationship("Payment", back_populates="transactions")

class Refund(Base):
    __tablename__ = "refunds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False)
    # 'processing' (sent to Bachs), 'succeeded', 'failed' (retry or pay manually). Legacy rows: 'requested'.
    status = Column(String(50), nullable=False, default="processing")
    reason = Column(String, nullable=True)
    order_id = Column(String(50), nullable=True, index=True)
    # The charge this refund returns money from: PaymentTransaction.provider_reference.
    charge_reference = Column(String(255), nullable=True, index=True)
    method = Column(String(20), nullable=True)  # 'bachs' (API) or 'manual' (bank transfer, recorded by an admin)
    provider_refund_id = Column(String(255), nullable=True, index=True)
    reference = Column(String(128), nullable=True, unique=True)  # ours, sent to Bachs; manual: the bank reference
    bearer = Column(String(20), nullable=True)  # who absorbs it: 'platform', 'merchant' or 'rider'
    reason_code = Column(String(40), nullable=True)
    failure_reason = Column(String(500), nullable=True)
    created_by = Column(String(255), nullable=True)  # admin user id, or 'system' for automatic refunds
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    payment = relationship("Payment", back_populates="refunds")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String, nullable=False, index=True)
    account_type = Column(String, nullable=False) # 'RESTAURANT_EARNINGS', 'PLATFORM_REVENUE', 'RIDER_EARNINGS', 'REFUND_REVERSAL'
    entry_type = Column(String, nullable=False, default="CREDIT") # 'CREDIT', 'DEBIT'
    amount = Column(Float, nullable=False)
    merchant_id = Column(String, nullable=True, index=True)
    rider_id = Column(String, nullable=True, index=True)
    reference = Column(String, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
