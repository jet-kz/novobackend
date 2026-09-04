from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.logging import setup_logging

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

setup_logging()

app = FastAPI(
    title="Novo Marketplace Backend",
    version="1.0.0",
    description="Production-ready modular monolith for a multi-sided marketplace"
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
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# API v1 Router Registration
# ─────────────────────────────────────────────────────────────────────────────
app.include_router(auth_router,       prefix="/api/v1/auth",        tags=["Authentication"])
app.include_router(users_router,      prefix="/api/v1/users",       tags=["User Profiles"])
app.include_router(uploads_router,    prefix="/api/v1/uploads",     tags=["File Uploads"])
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


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "app": "Novo Marketplace", "version": "1.0.0"}
