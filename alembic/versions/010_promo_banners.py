"""promo_banners for homepage ad/promo carousel

Revision ID: 010_promo_banners
Revises: 009_push_subscriptions
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "010_promo_banners"
down_revision: Union[str, None] = "009_push_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_banners",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(120), nullable=True),
        sa.Column("subtitle", sa.String(240), nullable=True),
        sa.Column("image", sa.String(500), nullable=False),
        sa.Column("cta_label", sa.String(40), nullable=True),
        sa.Column("link_url", sa.String(500), nullable=True),
        sa.Column("placement", sa.String(30), nullable=False, server_default="home", index=True),
        sa.Column("show_text", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("promo_banners")
