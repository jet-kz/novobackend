"""guest checkout, homepage catalog, menu section order, rider review, notifications

Revision ID: 007_guest_catalog_riders
Revises: 005_email_codes_rls
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "007_guest_catalog_riders"
down_revision: Union[str, None] = "005_email_codes_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORIES = [
    ("restaurant", "Food", "🍲", "Restaurants, grills, rice and local dishes"),
    ("supermarket", "Groceries", "🛒", "Fresh produce, pantry and household items"),
    ("pharmacy", "Pharmacy", "💊", "Medicine, first aid and personal care"),
    ("drinks", "Drinks", "🥤", "Soft drinks, juices, wine and spirits"),
    ("bakery", "Bakery", "🥐", "Bread, cakes, pies and pastries"),
    ("beauty", "Beauty", "✨", "Skincare, hair and cosmetics"),
    ("electronics", "Electronics", "📱", "Phones, accessories and gadgets"),
]


def upgrade() -> None:
    op.add_column("orders", sa.Column("customer_email", sa.String(255), nullable=True))
    op.add_column("orders", sa.Column("guest_token_hash", sa.String(64), nullable=True))

    # Existing riders are already working, so they start approved; new sign-ups default to pending.
    op.add_column("riders", sa.Column("approval_status", sa.String(20), nullable=False, server_default="approved"))
    op.alter_column("riders", "approval_status", server_default="pending")
    op.create_index("ix_riders_approval_status", "riders", ["approval_status"])
    op.add_column("riders", sa.Column("approval_note", sa.String(500), nullable=True))
    op.add_column("riders", sa.Column("id_document_url", sa.String(500), nullable=True))
    op.add_column("riders", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("product_categories", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False, index=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, server_default="message"),
        sa.Column("sender_id", sa.String(255), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )

    categories = op.create_table(
        "platform_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("icon", sa.String(255), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.bulk_insert(categories, [
        {"id": uuid.uuid4(), "slug": slug, "name": name, "icon": icon, "description": desc,
         "display_order": i, "is_active": True}
        for i, (slug, name, icon, desc) in enumerate(CATEGORIES, start=1)
    ])

    collections = op.create_table(
        "home_collections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("subtitle", sa.String(200), nullable=True),
        sa.Column("badge", sa.String(40), nullable=True),
        sa.Column("image", sa.String(500), nullable=True),
        sa.Column("target_category", sa.String(50), nullable=False, server_default="all"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.bulk_insert(collections, [
        {"id": uuid.uuid4(), "title": "Popular near you", "subtitle": "What people around you are ordering",
         "badge": None, "image": None, "target_category": "all", "display_order": 1, "is_active": True},
        {"id": uuid.uuid4(), "title": "Groceries & household", "subtitle": "Restock without leaving the house",
         "badge": None, "image": None, "target_category": "supermarket", "display_order": 2, "is_active": True},
    ])

    for table in ("notifications", "platform_categories", "home_collections"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("home_collections")
    op.drop_table("platform_categories")
    op.drop_table("notifications")
    op.drop_column("product_categories", "display_order")
    for col in ("reviewed_at", "id_document_url", "approval_note"):
        op.drop_column("riders", col)
    op.drop_index("ix_riders_approval_status", table_name="riders")
    op.drop_column("riders", "approval_status")
    op.drop_column("orders", "guest_token_hash")
    op.drop_column("orders", "customer_email")
