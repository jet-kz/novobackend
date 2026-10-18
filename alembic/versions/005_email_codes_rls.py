"""enable row level security on email_codes

Supabase exposes public tables over its REST API with the anon key. RLS with no policies
blocks that; the backend connects as the table owner and is unaffected.

Revision ID: 005_email_codes_rls
Revises: 004_add_email_codes
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005_email_codes_rls"
down_revision: Union[str, None] = "004_add_email_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE email_codes ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE email_codes DISABLE ROW LEVEL SECURITY")
