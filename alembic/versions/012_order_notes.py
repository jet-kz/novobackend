"""customer notes on orders and order items

Revision ID: 012_order_notes
Revises: 011_promotion_deleted_at
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_order_notes"
down_revision: Union[str, None] = "011_promotion_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("customer_note", sa.String(500), nullable=True))
    op.add_column("order_items", sa.Column("note", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("order_items", "note")
    op.drop_column("orders", "customer_note")
