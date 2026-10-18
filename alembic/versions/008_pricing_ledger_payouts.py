"""create pricing/ledger tables that were never migrated, plus Bachs payout tables

The pricing engine (commission/delivery/service-fee rules, snapshots, promotions) and ledger had
models but no migration, so every checkout failed with `relation "delivery_pricing_rules" does
not exist`. This creates them (skipping any that exist), seeds the default rules the code was
written for, and adds payout_accounts / settlements / withdrawals for Bachs Connect payouts.

Revision ID: 008_pricing_ledger_payouts
Revises: 007_guest_catalog_riders
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_pricing_ledger_payouts"
down_revision: Union[str, None] = "007_guest_catalog_riders"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "commission_rules", "delivery_pricing_rules", "service_fee_rules", "promotion_campaigns",
    "promotion_redemptions", "pricing_snapshots", "ledger_entries",
    "payout_accounts", "settlements", "withdrawals",
]


def upgrade() -> None:
    from app.core.database import Base
    import app.modules.pricing.models  # noqa: F401  (registers tables on Base.metadata)
    import app.modules.payments.models  # noqa: F401
    import app.modules.payouts.models  # noqa: F401

    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in NEW_TABLES]
    Base.metadata.create_all(bind, tables=tables, checkfirst=True)

    now = datetime.utcnow()
    if not bind.execute(sa.text("select 1 from commission_rules limit 1")).first():
        bind.execute(sa.text(
            "insert into commission_rules (id, name, rule_type, value, flat_fee, min_order_amount, is_active, created_at, updated_at) "
            "values (:id, 'Default commission (10%)', 'PERCENTAGE', 10, 0, 0, true, :now, :now)"
        ), {"id": str(uuid.uuid4()), "now": now})
    if not bind.execute(sa.text("select 1 from delivery_pricing_rules limit 1")).first():
        bind.execute(sa.text(
            "insert into delivery_pricing_rules (id, name, base_fee, per_km_fee, minimum_fee, maximum_fee, surge_multiplier, zone_name, is_active, created_at, updated_at) "
            "values (:id, 'Standard delivery', 500, 150, 500, 3000, 1, 'Delta State', true, :now, :now)"
        ), {"id": str(uuid.uuid4()), "now": now})
    if not bind.execute(sa.text("select 1 from service_fee_rules limit 1")).first():
        bind.execute(sa.text(
            "insert into service_fee_rules (id, name, fee_type, value, minimum_fee, maximum_fee, is_active, created_at, updated_at) "
            "values (:id, 'Service fee (2%)', 'PERCENTAGE', 2, 100, 1000, true, :now, :now)"
        ), {"id": str(uuid.uuid4()), "now": now})

    for name in NEW_TABLES:
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for name in ("withdrawals", "settlements", "payout_accounts"):
        op.drop_table(name)
    # Pricing/ledger tables are kept on downgrade: they hold order financial history.
