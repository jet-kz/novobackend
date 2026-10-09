"""Add missing product JSON columns

Revision ID: 003_add_product_json_columns
Revises: 09925ff34746
Create Date: 2026-10-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '003_add_product_json_columns'
down_revision: Union[str, None] = '09925ff34746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('protein_options', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('products', sa.Column('extras_options', sa.JSON(), nullable=True, server_default='[]'))
    op.add_column('products', sa.Column('specs', sa.JSON(), nullable=True, server_default='{}'))
    op.add_column('products', sa.Column('option_groups', sa.JSON(), nullable=True, server_default='[]'))


def downgrade() -> None:
    op.drop_column('products', 'option_groups')
    op.drop_column('products', 'specs')
    op.drop_column('products', 'extras_options')
    op.drop_column('products', 'protein_options')
