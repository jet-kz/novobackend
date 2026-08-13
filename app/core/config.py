import os
from dotenv import load_dotenv

load_dotenv()

# App general settings
PROJECT_NAME: str = "Novo Modular Monolith"
DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# Database / Supabase configurations
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = (
    os.getenv("SUPABASE_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or ""
)
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")

if not DATABASE_URL:
    raise EnvironmentError("DATABASE_URL was not set or empty in the environment.")
