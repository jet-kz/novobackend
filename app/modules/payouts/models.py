"""
Merchant & rider payouts through Bachs Connect.

Each merchant (owner) or rider gets a Bachs *connected account* (recipient). Novo collects every
customer payment on its own account; an admin "settles" what a payee has earned by transferring
it from Novo's balance to their connected account; the payee then withdraws to their bank.
"""
import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class PayoutAccount(Base):
    __tablename__ = "payout_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_type = Column(String(20), nullable=False)  # 'merchant' | 'rider'
    owner_id = Column(String(255), nullable=False, index=True)  # merchants.id or rider user id
    user_id = Column(String(255), nullable=False, index=True)  # the person who manages it
    bachs_account_id = Column(String(64), nullable=True, unique=True)
    status = Column(String(30), nullable=False, default="incomplete")  # incomplete | in_review | active | restricted
    transfers_enabled = Column(Boolean, nullable=False, default=False)
    payouts_enabled = Column(Boolean, nullable=False, default=False)
    requirements_due = Column(JSONB, nullable=True)  # list of fields Bachs still needs
    bank_name = Column(String(100), nullable=True)
    bank_code = Column(String(20), nullable=True)
    account_last4 = Column(String(4), nullable=True)
    account_name = Column(String(150), nullable=True)
    destination_id = Column(String(64), nullable=True)  # Bachs payout destination (pd_...)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Settlement(Base):
    """Money an admin moved from Novo's Bachs balance to a payee's connected account."""
    __tablename__ = "settlements"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payee_type = Column(String(20), nullable=False)  # 'merchant' | 'rider'
    payee_id = Column(String(255), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="NGN")
    status = Column(String(20), nullable=False, default="processing")  # processing | paid | failed
    bachs_transfer_id = Column(String(64), nullable=True, unique=True)
    failure_reason = Column(String(500), nullable=True)
    note = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)


class Withdrawal(Base):
    """A payee moving settled money from their connected account to their bank."""
    __tablename__ = "withdrawals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payout_account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="NGN")
    status = Column(String(20), nullable=False, default="pending")  # pending | processing | completed | failed
    bachs_payout_id = Column(String(64), nullable=True, unique=True)
    failure_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
