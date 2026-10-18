import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core import config
from app.core.database import engine
from app.core.logging import setup_logging
from app.core.mailer import mail_enabled

from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.merchants.router import router as merchants_router
from app.modules.stores.router import router as stores_router
from app.modules.products.router import router as products_router
from app.modules.carts.router import router as carts_router
from app.modules.orders.router import router as orders_router
from app.modules.payments.router import router as payments_router
from app.modules.deliveries.router import router as deliveries_router
from app.modules.riders.router import router as riders_router
from app.modules.addresses.router import router as addresses_router
from app.modules.wallets.router import router as wallets_router
from app.modules.inventory.router import router as inventory_router
from app.modules.analytics.router import router as analytics_router
from app.modules.uploads.router import router as uploads_router
from app.modules.pricing.router import router as pricing_router
from app.modules.catalog.router import router as catalog_router
from app.modules.notifications.router import router as notifications_router
from app.modules.payouts.router import router as payouts_router
from app.modules.admin.router import router as admin_router

setup_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    from app.modules.auth.models import EmailCode

    # Same table as alembic revision 004; created here too so auth works before migrations run.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: EmailCode.__table__.create(sync_conn, checkfirst=True))
    except Exception:
        logging.getLogger("novo").exception("Could not ensure email_codes table")
    try:
        from app.modules.uploads.router import ensure_buckets

        await asyncio.to_thread(ensure_buckets)
    except Exception:
        logging.getLogger("novo").exception("Could not ensure storage buckets")
    if not mail_enabled():
        logging.getLogger("novo").warning(
            "No email provider configured (RESEND_API_KEY or SMTP_*); auth codes fall back to Supabase's mailer "
            "and notification emails are skipped."
        )
    yield


app = FastAPI(
    title="Novo Marketplace Backend",
    version="1.0.0",
    description="Production-ready modular monolith for a multi-sided marketplace",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "https://novobackend.onrender.com",
        "https://novo-flame.vercel.app",
        "https://www.novong.com",
        "https://novong.com",
        config.FRONTEND_URL,
    ],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from fastapi.responses import JSONResponse
import socket

@app.exception_handler(socket.gaierror)
async def socket_gaierror_handler(request: Request, exc: socket.gaierror):
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "message": "Database connection error (getaddrinfo failed). Please verify internet/network connection to database server.",
            "detail": str(exc)
        }
    )

# ─────────────────────────────────────────────────────────────────────────────
# API v1 Router Registration
# ─────────────────────────────────────────────────────────────────────────────
app.include_router(auth_router,       prefix="/api/v1/auth",        tags=["Authentication"])
app.include_router(users_router,      prefix="/api/v1/users",       tags=["User Profiles"])
app.include_router(uploads_router,    prefix="/api/v1/uploads",     tags=["File Uploads"])
app.include_router(pricing_router,    prefix="/api/v1/pricing",     tags=["Pricing & Promotions Engine"])
app.include_router(merchants_router,  prefix="/api/v1/merchants",   tags=["Merchants"])
app.include_router(stores_router,     prefix="/api/v1/stores",      tags=["Stores"])
app.include_router(products_router,   prefix="/api/v1/products",    tags=["Products"])
app.include_router(carts_router,      prefix="/api/v1/carts",       tags=["Carts"])
app.include_router(orders_router,     prefix="/api/v1/orders",      tags=["Orders"])
app.include_router(payments_router,   prefix="/api/v1/payments",    tags=["Payments"])
app.include_router(deliveries_router, prefix="/api/v1/deliveries",  tags=["Deliveries"])
app.include_router(riders_router,     prefix="/api/v1/riders",      tags=["Riders"])
app.include_router(addresses_router,  prefix="/api/v1/addresses",   tags=["Addresses"])
app.include_router(wallets_router,    prefix="/api/v1/wallets",     tags=["Wallets"])
app.include_router(inventory_router,  prefix="/api/v1/inventory",   tags=["Inventory"])
app.include_router(analytics_router,  prefix="/api/v1/analytics",   tags=["Analytics"])
app.include_router(catalog_router,    prefix="/api/v1/catalog",     tags=["Homepage Catalog"])
app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(payouts_router,    prefix="/api/v1/payouts",     tags=["Merchant & Rider Payouts"])
app.include_router(admin_router,      prefix="/api/v1/admin",       tags=["Admin Console"])


@app.get("/", tags=["Health"])
@app.head("/", tags=["Health"])
@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "app": "Novo Marketplace API", "version": "1.0.0"}
