# Novo Modular Monolith Backend — System & API Documentation

Welcome to the central system architecture & API registry for the **Novo Modular Monolith Backend**. This system is built as a category-agnostic, multi-sided marketplace backend (similar to Glovo or Uber Eats) using **FastAPI** (Python) and **PostgreSQL (Supabase)**.

---

## 1. System Architecture Overview

The backend is built as a **Modular Monolith** where all domain code is isolated within clean folder structures in `app/modules/`. This design keeps dependencies separate while maintaining the ease of running and deploying a single monolith.

### Core Stack
- **API Runtime:** FastAPI (Python 3.11+)
- **Database Engine:** Supabase PostgreSQL 15+ + PostGIS (for radius searches and location-aware computations).
- **ORM & Driver:** SQLAlchemy 2.0 (using `asyncpg` for async I/O drivers).
- **Authentication:** Supabase JWT Verification with custom RBAC (Role-Based Access Control) injected via backend middleware.
- **Image Processing:** On-the-fly resizing and compression utilizing `Pillow`.

---

## 2. Implementation Completeness & Status

Here is the current implementation parity of the system modules:

| Module | Core Logic & Service | Database Schema | API Endpoints | Status |
| :--- | :--- | :--- | :--- | :--- |
| **`auth`** | 100% | 100% | 100% | ✅ Fully Functional (Signup, login, OTP verification) |
| **`users`** | 100% | 100% | 100% | ✅ Profile updates and avatar integration |
| **`merchants`** | 100% | 100% | 100% | ✅ Merchant account controls, onboarding approval |
| **`stores`** | 100% | 100% | 100% | ✅ Store profiling, pricing rules, geospatial coordinates |
| **`products`** | 100% | 100% | 100% | ✅ Categories, product options, configurations |
| **`carts`** | 100% | 100% | 100% | ✅ Cart items grouping (Restricted to single Store) |
| **`orders`** | 100% | 100% | 100% | ✅ Orders, state machine transitions, cancel logging |
| **`payments`** | 100% | 100% | 100% | ✅ Transaction logging, refunds workflow |
| **`wallets`** | 100% | 100% | 100% | ✅ Double-entry ledger (credits, debits) |
| **`deliveries`** | 100% | 100% | 100% | ✅ Logistic tasks, rider assignments, driver GPS logs |
| **`riders`** | 100% | 100% | 100% | ✅ Rider vehicle profiles, status toggles, ratings |
| **`addresses`** | 100% | 100% | 100% | ✅ User address books, default marker setting |
| **`audit`** | 100% | 100% | Internal | ✅ Background audit logs for admin entities |
| **`inventory`** | 100% | 100% | 100% | ✅ **NEW:** Live quantities + **CSV Bulk Import (with product image URL mapping)** |
| **`uploads`** | 100% | 100% | 100% | ✅ **NEW:** Supabase integration + **Pillow Image Compression & UUID unique naming** |
| **`analytics`** | 100% | 100% | 100% | ✅ Sales statistics aggregates |

---

## 3. Database Schema Speclist (27 Tables)

All SQLAlchemy database models inherit from `app.core.database.Base`. Columns, types, and primary relation constraints are detailed below:

### Addresses Module
- **Table: `addresses`**
  - `id` (UUID, PK) — Unique primary identifier.
  - `user_id` (VARCHAR) — Foreign key mapping to Supabase user identity.
  - `label` (VARCHAR) — E.g., 'Home', 'Office'.
  - `address_text` (VARCHAR) — Full shipping address string.
  - `location` (PostGIS Geometry(Point, 4326)) — Spherical coordinate point.
  - `delivery_instructions` (VARCHAR) — Note to rider/driver.
  - `is_default` (BOOLEAN) — Default shipping option.
  - `is_deleted` (BOOLEAN) — Soft delete toggle.
  - `created_at` (TIMESTAMP) — Creation time.

### Audit Module
- **Table: `audit_logs`**
  - `id` (UUID, PK)
  - `actor` (VARCHAR) — Actor ID who performed the action.
  - `action` (VARCHAR) — E.g., 'update_merchant_status'.
  - `entity_type` (VARCHAR) — Target table name.
  - `entity_id` (UUID) — Target record reference.
  - `action_metadata` (JSONB) — Raw parameter payloads.
  - `timestamp` (TIMESTAMP)

### Authentication & Roles Module
- **Table: `roles`**
  - `id` (UUID, PK)
  - `name` (VARCHAR) — Unique role indicator (`customer`, `rider`, `merchant_owner`, `store_manager`, `dispatcher`).
- **Table: `permissions`**
  - `id` (UUID, PK)
  - `description` (VARCHAR) — E.g. 'products:create'.
- **Table: `user_roles`**
  - `user_id` (VARCHAR, PK/FK)
  - `role_id` (UUID, PK/FK)
- **Table: `role_permissions`**
  - `role_id` (UUID, PK/FK)
  - `permission_id` (UUID, PK/FK)

### Carts Module
- **Table: `carts`**
  - `id` (UUID, PK)
  - `customer_id` (VARCHAR) — Owner user ID.
  - `store_id` (UUID, FK) — Associated store (Strict constraint: single merchant context).
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)
- **Table: `cart_items`**
  - `id` (UUID, PK)
  - `cart_id` (UUID, FK) — Target active cart parent.
  - `product_id` (UUID, FK) — Item from products table.
  - `quantity` (INTEGER) — Stock count.
  - `addons` (JSONB) — Customization choices snapshot.

### Inventories Module
- **Table: `inventory_items`**
  - `id` (UUID, PK)
  - `product_id` (UUID, FK, Unique) — Parent product reference.
  - `quantity` (INTEGER) — Stock count on hand.
  - `reserved_quantity` (INTEGER) — Allocated in pending orders.
  - `low_stock_threshold` (INTEGER) — Level triggering reorder indicators.
  - `updated_at` (TIMESTAMP)
- **Table: `inventory_adjustments`**
  - `id` (UUID, PK)
  - `inventory_item_id` (UUID, FK)
  - `adjustment_type` (VARCHAR) — 'restock', 'sale', 'adjustment', 'damage', 'import'.
  - `quantity` (INTEGER) — Quantity diff (+/-).
  - `reason` (VARCHAR) — Note (e.g. 'CSV bulk import').
  - `created_at` (TIMESTAMP)

### Merchants Module
- **Table: `merchants`**
  - `id` (UUID, PK)
  - `name` (VARCHAR) — Legal business label.
  - `owner_id` (VARCHAR) — Supabase user ID of owner.
  - `status` (VARCHAR) — 'pending', 'approved', 'suspended'.
  - `is_deleted` (BOOLEAN) — Soft delete check.
  - `created_at` (TIMESTAMP)

### Stores Module
- **Table: `stores`**
  - `id` (UUID, PK)
  - `merchant_id` (UUID, FK)
  - `name` (VARCHAR) — Retail branch name.
  - `slug` (VARCHAR) — Slug URL.
  - `store_type` (VARCHAR) — 'restaurant', 'grocery', 'pharmacy'.
  - `logo` (VARCHAR) — Logo public path link.
  - `banner` (VARCHAR) — Hero banner image URL.
  - `address` (VARCHAR)
  - `location` (Geometry(Point, 4326)) — Geographical coordinate.
  - `is_open` (BOOLEAN)
  - `is_verified` (BOOLEAN)
  - `is_deleted` (BOOLEAN)
  - `settings` (JSONB) — Operating hours constraints.
  - `phone` (VARCHAR)
  - `created_at` (TIMESTAMP)
- **Table: `pricing_rules`**
  - `id` (UUID, PK)
  - `store_id` (UUID, FK)
  - `rule_type` (VARCHAR) — 'flat_delivery', 'multiplier'.
  - `parameters` (JSONB) — Values mapping rules.
  - `currency` (VARCHAR)
  - `is_active` (BOOLEAN)

### Products Module
- **Table: `product_categories`**
  - `id` (UUID, PK)
  - `store_id` (UUID, FK) — Associated store hierarchy.
  - `name` (VARCHAR) — Category label (e.g. 'Sides').
  - `slug` (VARCHAR)
  - `is_deleted` (BOOLEAN)
  - `created_at` (TIMESTAMP)
- **Table: `products`**
  - `id` (UUID, PK)
  - `store_id` (UUID, FK)
  - `category_id` (UUID, FK)
  - `name` (VARCHAR)
  - `description` (TEXT)
  - `price` (FLOAT) — Item base rate.
  - `currency` (VARCHAR) — Standard code e.g. 'USD', 'NGN'.
  - `image` (VARCHAR) — Configured asset URL page.
  - `in_stock` (BOOLEAN)
  - `is_deleted` (BOOLEAN)
  - `rating` (FLOAT)
  - `preparation_time_minutes` (INTEGER)
  - `created_at` (TIMESTAMP)
- **Table: `product_options`**
  - `id` (UUID, PK)
  - `product_id` (UUID, FK)
  - `name` (VARCHAR) — E.g. 'Extra Cheese'.
  - `price` (FLOAT)
  - `currency` (VARCHAR)

### Orders Module
- **Table: `orders`**
  - `id` (UUID, PK)
  - `customer_id` (VARCHAR)
  - `customer_name` (VARCHAR)
  - `customer_phone` (VARCHAR)
  - `store_id` (UUID, FK)
  - `address_id` (UUID, FK)
  - `subtotal` (FLOAT)
  - `delivery_fee` (FLOAT)
  - `service_fee` (FLOAT)
  - `tax` (FLOAT)
  - `tip` (FLOAT)
  - `total` (FLOAT)
  - `payment_status` (VARCHAR) — 'pending', 'paid', 'failed', 'refunded'.
  - `status` (VARCHAR) — 'cart', 'pending', 'accepted', 'preparing', 'ready_for_pickup', 'in_transit', 'delivered', 'cancelled'.
  - `payment_method` (VARCHAR) — 'card', 'wallet', 'cash_on_delivery'.
  - `currency` (VARCHAR)
  - `delivery_longitude` (FLOAT)
  - `delivery_latitude` (FLOAT)
  - `delivery_address` (VARCHAR)
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)
- **Table: `order_items`**
  - `id` (UUID, PK)
  - `order_id` (UUID, FK)
  - `product_id` (UUID)
  - `name` (VARCHAR) — Snapshot product name at timestamp.
  - `price` (FLOAT) — Snapshot rate.
  - `quantity` (INTEGER)
  - `addons` (JSONB)
- **Table: `order_status_history`**
  - `id` (UUID, PK)
  - `order_id` (UUID, FK)
  - `old_status` (VARCHAR)
  - `new_status` (VARCHAR)
  - `changed_by_id` (VARCHAR)
  - `cancellation_reason` (VARCHAR)
  - `created_at` (TIMESTAMP)

### Payments Module
- **Table: `payments`**
  - `id` (UUID, PK)
  - `order_id` (UUID, FK)
  - `amount` (FLOAT)
  - `currency` (VARCHAR)
  - `status` (VARCHAR) — 'pending', 'succeeded', 'failed', 'refunded'.
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)
- **Table: `payment_transactions`**
  - `id` (UUID, PK)
  - `payment_id` (UUID, FK)
  - `txn_type` (VARCHAR) — 'charge', 'refund', 'payout'.
  - `provider` (VARCHAR) — 'stripe', 'paystack'.
  - `provider_reference` (VARCHAR)
  - `amount` (FLOAT)
  - `currency` (VARCHAR)
  - `status` (VARCHAR)
  - `provider_metadata` (JSONB)
  - `created_at` (TIMESTAMP)
- **Table: `refunds`**
  - `id` (UUID, PK)
  - `payment_id` (UUID, FK)
  - `amount` (FLOAT)
  - `currency` (VARCHAR)
  - `status` (VARCHAR) — 'requested', 'processed', 'failed'.
  - `reason` (VARCHAR)
  - `created_at` (TIMESTAMP)

### Wallets Module (Ledger)
- **Table: `wallets`**
  - `id` (UUID, PK)
  - `holder_id` (VARCHAR) — Account holder user ID/store ID.
  - `currency` (VARCHAR) — Wallet base denom (e.g. 'NGN').
  - `balance` (FLOAT) — Live balance state (read-only direct target).
  - _Unique constraint:_ `(holder_id, currency)` to prevent multiple balance duplicate wallets.
- **Table: `wallet_transactions`**
  - `id` (UUID, PK)
  - `wallet_id` (UUID, FK)
  - `amount` (FLOAT) — Value.
  - `direction` (VARCHAR) — 'credit' (add) or 'debit' (remove).
  - `txn_type` (VARCHAR) — 'payout', 'purchase', 'earnings', 'refund', 'deposit'.
  - `reference` (VARCHAR) — Transaction ID of trace event.
  - `created_at` (TIMESTAMP)

### Deliveries Module
- **Table: `deliveries`**
  - `id` (UUID, PK)
  - `order_id` (UUID, FK)
  - `rider_id` (UUID, FK)
  - `pickup_location` (Geometry(Point, 4326))
  - `dropoff_location` (Geometry(Point, 4326))
  - `status` (VARCHAR) — 'searching', 'assigned', 'picked_up', 'delivered', 'failed'.
  - `fee` (FLOAT) — Charged to buyer.
  - `rider_earnings` (FLOAT) — Distributed amount to agent.
  - `currency` (VARCHAR)
  - `assigned_at` (TIMESTAMP)
  - `picked_up_at` (TIMESTAMP)
  - `delivered_at` (TIMESTAMP)
  - `created_at` (TIMESTAMP)
- **Table: `delivery_assignments`**
  - `id` (UUID, PK)
  - `delivery_id` (UUID, FK)
  - `rider_id` (UUID, FK)
  - `status` (VARCHAR) — 'offered', 'accepted', 'rejected', 'expired'.
  - `offered_at` (TIMESTAMP)
  - `responded_at` (TIMESTAMP)
  - `expires_at` (TIMESTAMP)
- **Table: `rider_location_history`**
  - `id` (UUID, PK)
  - `rider_id` (UUID)
  - `location` (Geometry(Point, 4326))
  - `captured_at` (TIMESTAMP)

### Riders Module
- **Table: `riders`**
  - `id` (UUID, PK) — Shared user profile ID.
  - `vehicle_type` (VARCHAR) — 'motorcycle', 'bicycle', 'car'.
  - `vehicle_plate` (VARCHAR)
  - `status` (VARCHAR) — 'offline', 'online', 'busy'.
  - `rating` (FLOAT)
  - `total_deliveries` (INTEGER)
  - `is_deleted` (BOOLEAN)
  - `last_location` (Geometry(Point, 4326))
  - `updated_at` (TIMESTAMP)

### User Profiles Module
- **Table: `user_profiles`**
  - `user_id` (VARCHAR, PK) — Maps to Auth ID.
  - `full_name` (VARCHAR)
  - `phone` (VARCHAR)
  - `avatar_url` (VARCHAR)
  - `is_active` (BOOLEAN)
  - `created_at` (TIMESTAMP)
  - `updated_at` (TIMESTAMP)

---

## 4. Complete API Route Reference

Below is a complete description of all routers registered under `/api/v1/`:

### Authentication (`/api/v1/auth`)
- `POST /api/v1/auth/signup` — Sign up a new customer or merchant.
- `POST /api/v1/auth/login` — Sign in and obtain JWT access token.
- `POST /api/v1/auth/verify-otp` — Verify phone/email OTP for activation.
- `GET /api/v1/auth/me` — Retrieve token claims and global user details.

### Users Profile (`/api/v1/users`)
- `GET /api/v1/users/me` — Fetch currently authenticated user's profile database records.
- `PUT /api/v1/users/me` — Edit user profile metadata.
- `POST /api/v1/users/me/avatar` — Upload avatar to Supabase and save public link on profile.
- `DELETE /api/v1/users/me` — Soft-delete/deactivate user account.

### Addresses Routing (`/api/v1/addresses`)
- `GET /api/v1/addresses` — List saved shipping address locations.
- `POST /api/v1/addresses` — Save new address options with geometric coordinates.
- `PUT /api/v1/addresses/{address_id}` — Edit details of an address.
- `PATCH /api/v1/addresses/{address_id}/default` — Set the active default shipping address.
- `DELETE /api/v1/addresses/{address_id}` — Remove an address bookmark.

### Merchants Management (`/api/v1/merchants`)
- `GET /api/v1/merchants` — List onboarding merchants.
- `GET /api/v1/merchants/{merchant_id}` — Get single merchant details.
- `POST /api/v1/merchants` — Register a corporate entity.
- `PUT /api/v1/merchants/{merchant_id}` — Edit merchant parameters.
- `PATCH /api/v1/merchants/{merchant_id}/status` — Admin activation/deactivation hook.
- `GET /api/v1/merchants/{merchant_id}/stores` — Direct query list of stores owned by a merchant.

### Stores Profiling (`/api/v1/stores`)
- `GET /api/v1/stores` — Query list of stores. Supports filtering options (nearby stores via radial coordinates, open/closed, type).
- `GET /api/v1/stores/{store_id}` — Retrieve exact store details.
- `POST /api/v1/stores` — Onboard store locations for a merchant.
- `PUT /api/v1/stores/{store_id}` — Edit address coordinates or settings object.
- `PATCH /api/v1/stores/{store_id}/toggle-open` — Set store online/offline.
- `DELETE /api/v1/stores/{store_id}` — Soft delete a store location.

### Product Catalogs (`/api/v1/products`)
- `GET /api/v1/products` — Retrieve products catalog of a store category.
- `GET /api/v1/products/categories` — Get catalog category listings.
- `GET /api/v1/products/{product_id}` — Get specific product item details.
- `POST /api/v1/products` — Create new menu catalog items.
- `PUT /api/v1/products/{product_id}` — Edit details of a product.
- `PATCH /api/v1/products/{product_id}/toggle-stock` — Quick stock status toggle.
- `DELETE /api/v1/products/{product_id}` — Soft-delete menu catalog entry.

### Shopping Cart (`/api/v1/carts`)
- `GET /api/v1/carts` — Get item records matching user context.
- `POST /api/v1/carts/items` — Add product options and quantities. Emits 400 if product doesn't reside within same store context.
- `PATCH /api/v1/carts/items/{item_id}` — Increment/decrement item quantity.
- `DELETE /api/v1/carts/items/{item_id}` — Remove item from shopping cart.
- `DELETE /api/v1/carts` — Empty complete active session cart.

### Orders Processing (`/api/v1/orders`)
- `GET /api/v1/orders` — List past and active orders for user.
- `GET /api/v1/orders/{order_id}` — Retrieve detailed bill checkout item copy.
- `POST /api/v1/orders` — Final check, locks cart status, maps to payment options.
- `PATCH /api/v1/orders/{order_id}/status` — Fast order status modification.
- `POST /api/v1/orders/{order_id}/cancel` — Trigger cancellation, audits transaction rollback.
- `GET /api/v1/orders/{order_id}/history` — Timeline history of transitions.

### Payments Processing (`/api/v1/payments`)
- `GET /api/v1/payments/{order_id}` — Retrieve transaction status matching order.
- `POST /api/v1/payments` — Initialize gateway intents (Paystack/Stripe/Flutterwave).
- `POST /api/v1/payments/{payment_id}/transactions` — Log transaction responses from webhooks.
- `POST /api/v1/payments/{payment_id}/refunds` — Initialize core order refund workflow.
- `GET /api/v1/payments/{payment_id}/refunds` — List refunds logged for a specific payment.
- `PATCH /api/v1/payments/{payment_id}/refunds/{refund_id}/process` — Admin execution check of refund status.

### Ledger Wallets (`/api/v1/wallets`)
- `GET /api/v1/wallets` — Retrieve list of wallets matching distinct user currencies.
- `GET /api/v1/wallets/{currency}/balance` — Get target wallet balance.
- `GET /api/v1/wallets/{currency}/transactions` — Query audit ledger logs list.
- `POST /api/v1/wallets/credit` — Add funds (credits) via gateway confirmations.
- `POST /api/v1/wallets/debit` — Withdraw/debited funds (for buying/payouts).

### Logistic Assignments (`/api/v1/deliveries`)
- `GET /api/v1/deliveries/{delivery_id}` — Details of current delivery tracking.
- `GET /api/v1/deliveries/order/{order_id}` — Get logistics tracking using order reference.
- `POST /api/v1/deliveries` — Create delivery execution sheet.
- `POST /api/v1/deliveries/{delivery_id}/assign/{rider_id}` — Assign matching rider.
- `PATCH /api/v1/deliveries/{delivery_id}/status` — Driver progress triggers.
- `POST /api/v1/deliveries/rider/location` — Live GPS polling endpoint.

### Rider Profiles (`/api/v1/riders`)
- `GET /api/v1/riders` — List active online drivers.
- `GET /api/v1/riders/{rider_id}` — Profile vehicle stats info.
- `POST /api/v1/riders` — Configure rider account profile.
- `PATCH /api/v1/riders/me/status` — Online/Offline status switch toggles.
- `GET /api/v1/riders/me/deliveries` — History of orders completed.
- `DELETE /api/v1/riders/{rider_id}` — Deactivate/Offboard rider profile.

### File Uploads (`/api/v1/uploads`)
- `POST /api/v1/uploads` — Uploads an image. Compresses it (Pillow) and saves on Supabase Storage using a random UUID filename wrapper to avoid user collisions.
- `POST /api/v1/uploads/bulk` — Uploads a batch list of multiple image files with on-the-fly compression.
- `DELETE /api/v1/uploads` — Deletes target file index on Supabase storage using bucket name and file path variables.

### Inventory Manager (`/api/v1/inventory`)
- `GET /api/v1/inventory/product/{product_id}` — Current inventory levels.
- `POST /api/v1/inventory` — Initialize an inventory log tracker.
- `POST /api/v1/inventory/product/{product_id}/adjust` — Restock or deduct quantity logs.
- `GET /api/v1/inventory/low-stock` — Trigger stock level warnings list.
- `POST /api/v1/inventory/import` — **CSV file bulk import.** Automatically parses columns for `product_id`, `quantity`, `low_stock_threshold`, and optional product `image` URLs. Updates inventory levels, adds transaction audits, and updates target catalog product images on matching records.

### Analytics (`/api/v1/analytics`)
- `GET /api/v1/analytics` — Dynamic statistics engine for order logs, revenue amounts, and merchant payouts.
