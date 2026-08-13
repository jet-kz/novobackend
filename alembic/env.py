import os
import sys
from logging.config import fileConfig
from dotenv import load_dotenv

# Add parent directory to sys.path to allow importing project modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

load_dotenv()


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from app.core.database import Base
from app.modules.auth.models import Role, Permission, UserRole
from app.modules.addresses.models import Address
from app.modules.merchants.models import Merchant
from app.modules.stores.models import Store, PricingRule
from app.modules.products.models import Product, ProductOption, ProductCategory
from app.modules.carts.models import Cart, CartItem
from app.modules.orders.models import Order, OrderItem, OrderStatusHistory
from app.modules.payments.models import Payment, PaymentTransaction, Refund
from app.modules.riders.models import RiderProfile
from app.modules.deliveries.models import Delivery, DeliveryAssignment, RiderLocationHistory
from app.modules.wallets.models import Wallet, WalletTransaction
from app.modules.inventory.models import InventoryItem, InventoryAdjustment
from app.modules.audit.models import AuditLog
from app.modules.users.models import UserProfile

target_metadata = Base.metadata


# get DATABASE_URL from environment variable
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable not set")

# Ensure we use the asyncpg dialect
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

config.set_main_option('sqlalchemy.url', database_url)

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    import asyncio
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

