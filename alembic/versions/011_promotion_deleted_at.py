"""promotion_campaigns.deleted_at for archiving used store promo codes

Revision ID: 011_promotion_deleted_at
Revises: 010_promo_banners
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_promotion_deleted_at"
down_revision: Union[str, None] = "010_promo_banners"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promotion_campaigns", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_promotion_campaigns_merchant", "promotion_campaigns", ["applicable_merchant_id"])


def downgrade() -> None:
    op.drop_index("ix_promotion_campaigns_merchant", table_name="promotion_campaigns")
    op.drop_column("promotion_campaigns", "deleted_at")
