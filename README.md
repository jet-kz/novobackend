# Novo Marketplace Backend

This repository contains the backend service for **Novo**, a multi-sided marketplace (Glovo/Uber Eats-like) supporting Customers, Merchants, and Riders. It is structured as a **Modular Monolith** using **FastAPI** (Python 3.11+) and **PostgreSQL (Supabase)**.

---

## Features Implemented
- **Modular Architecture:** 15 modular domains (auth, users, merchants, stores, products, carts, orders, payments, wallets, deliveries, riders, addresses, inventory, uploads, analytics) isolating models, routes, and business layers.
- **Supabase Authentication:** Seamless JWT authentication decoding in backend custom middlewares.
- **Ledger Wallets:** Immutable double-entry credits/debits balances keeping distinct wallets per currency.
- **Geospatial (RADIUS and PostGIS):** Radius store searching and driver tracking utilizing location points on PostgreSQL database.
- **Image Optimization (New):** Pillow-based on-the-fly resizing and quality compressions for single and bulk uploads.
- **Bulk Inventory CSV Imports (New):** Upload CSV spreadsheets to adjust item counts, add logging, and update catalog product image URLs in one API invocation.

---

## Directory Architecture

```text
novobackend/
│
├── app/
│   ├── core/               # Database config, security, logging
│   ├── integrations/       # Supabase service clients
│   ├── modules/            # Domain Modules
│   │   ├── auth/           # RBAC rules, login, signup
│   │   ├── inventory/      # Live levels, CSV import logic
│   │   ├── uploads/        # PIL image compression
│   │   └── ...             # Other 12 domain folders
│   └── main.py             # FastAPI App definition
│
├── alembic/                # DB migrations scripts
├── requirements.txt        # Backend dependencies
└── README.md
```

Detailed endpoints and database spec lists can be found in [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

---

## Installation & Setup

### 1. Pre-requisites
- **Python 3.11+**
- **Git**
- A **Supabase** account/project with a PostgreSQL database.

### 2. Clone and Setup Environment
```bash
git clone <your-repository-url>
cd novobackend
```

### 3. Create and Activate Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements.txt
```

### 5. Setup Environment Variables
Copy `.env.example` to `.env` and fill in the credentials:
```bash
# Windows cmd
copy .env.example .env

# PowerShell / bash
cp .env.example .env
```
Open `.env` and specify:
- `DATABASE_URL`: Connection string to your PostgreSQL (Supabase).
- `SUPABASE_URL` and `SUPABASE_KEY` (Anon/Service Role keys).
- `SUPABASE_JWT_SECRET` (For decoding JWT tokens securely).

### 6. Run Migrations
Run your active migrations via Alembic:
```bash
alembic upgrade head
```

---

## Running the Development Server

Start uvicorn reload engine:
```bash
uvicorn app.main:app --reload
```
- Interactive Swagger API docs: `http://127.0.0.1:8000/docs`
- Redoc documentation: `http://127.0.0.1:8000/redoc`

---

## Creating the GitHub Repository (Must-Read before pushing)

Before you initialize and push this codebase to a git repository, pay attention to the security and ignored files:

### 1. Ensure secrets are ignored
Make sure `.env` is NOT checked into Git. Use the newly created local `.gitignore` which automatically blocks track directories like `venv/`, `.env`, `__pycache__/`, and `.idea/` / `.vscode/`.

### 2. Repo Setup Commands
Run the following commands inside `novobackend/`:
```bash
# Initialize git
git init

# Add all files (will exclude folders defined in .gitignore)
git add .

# Create initial commit
git commit -m "Initial commit for Novo Modular Monolith Backend"

# Create a new repository on GitHub (without adding README or gitignore on GitHub)
# Then link database and push:
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git branch -M main
git push -u origin main
```
