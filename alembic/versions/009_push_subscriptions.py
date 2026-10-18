"""push_subscriptions for web push notifications

Revision ID: 009_push_subscriptions
Revises: 008_pricing_ledger_payouts
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "009_push_subscriptions"
down_revision: Union[str, None] = "008_pricing_ledger_payouts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=True, index=True),
        sa.Column("guest_order_id", sa.String(50), nullable=True, index=True),
        sa.Column("open_url", sa.String(500), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("push_subscriptions")
