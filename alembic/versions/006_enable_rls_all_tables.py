"""enable row level security on every app table

Without RLS, Supabase's REST API lets anyone holding the anon key read and write these
tables directly (orders, wallets, user_roles, ...). No policies are added, so that path is
closed entirely. The backend connects as `postgres` (BYPASSRLS) and is unaffected.

Revision ID: 006_enable_rls_all_tables
Revises: 009_push_subscriptions
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006_enable_rls_all_tables"
down_revision: Union[str, None] = "009_push_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# spatial_ref_sys belongs to PostGIS / supabase_admin and only holds public reference data.
_SELECT_TABLES = """
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'public' AND tableowner = current_user AND tablename <> 'spatial_ref_sys'
"""


def _set_rls(enabled: bool) -> None:
    action = "ENABLE" if enabled else "DISABLE"
    op.execute(f"""
        DO $$
        DECLARE t text;
        BEGIN
            FOR t IN {_SELECT_TABLES} LOOP
                EXECUTE format('ALTER TABLE public.%I {action} ROW LEVEL SECURITY', t);
            END LOOP;
        END $$;
    """)


def upgrade() -> None:
    _set_rls(True)


def downgrade() -> None:
    _set_rls(False)
