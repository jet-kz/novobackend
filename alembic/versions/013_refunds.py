"""refunds through Bachs: link refunds to orders and charges, track status, who absorbs the cost

Revision ID: 013_refunds
Revises: 012_order_notes
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_refunds"
down_revision: Union[str, None] = "012_order_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = [
    sa.Column("order_id", sa.String(50), nullable=True),
    sa.Column("charge_reference", sa.String(255), nullable=True),
    sa.Column("method", sa.String(20), nullable=True),
    sa.Column("provider_refund_id", sa.String(255), nullable=True),
    sa.Column("reference", sa.String(128), nullable=True),
    sa.Column("bearer", sa.String(20), nullable=True),
    sa.Column("reason_code", sa.String(40), nullable=True),
    sa.Column("failure_reason", sa.String(500), nullable=True),
    sa.Column("created_by", sa.String(255), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("refunds", column)
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"])
    op.create_index("ix_refunds_charge_reference", "refunds", ["charge_reference"])
    op.create_index("ix_refunds_provider_refund_id", "refunds", ["provider_refund_id"])
    op.create_unique_constraint("uq_refunds_reference", "refunds", ["reference"])
    op.alter_column("refunds", "status", server_default="processing")

    # Existing rows: admin-recorded refunds ('processed') were manual and already done.
    op.execute("""
        update refunds r set order_id = p.order_id from payments p where p.id = r.payment_id and r.order_id is null
    """)
    op.execute("""
        update refunds set status = 'succeeded', method = 'manual', bearer = 'platform', completed_at = created_at
        where status = 'processed'
    """)
    # 'requested' rows came from an old customer endpoint that never moved money.
    op.execute("update refunds set status = 'failed', failure_reason = 'Old request, never processed' where status = 'requested'")


def downgrade() -> None:
    op.execute("update refunds set status = 'processed' where status = 'succeeded'")
    op.drop_constraint("uq_refunds_reference", "refunds", type_="unique")
    op.drop_index("ix_refunds_provider_refund_id", table_name="refunds")
    op.drop_index("ix_refunds_charge_reference", table_name="refunds")
    op.drop_index("ix_refunds_order_id", table_name="refunds")
    for column in reversed(COLUMNS):
        op.drop_column("refunds", column.name)
