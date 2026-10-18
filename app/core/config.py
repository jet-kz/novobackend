import os
from dotenv import load_dotenv

load_dotenv()

# App general settings
PROJECT_NAME: str = "Novo Modular Monolith"
DEBUG: bool = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
# Never enable in production. When true, missing/invalid JWTs impersonate a guest customer.
ALLOW_INSECURE_DEV_AUTH: bool = os.getenv("ALLOW_INSECURE_DEV_AUTH", "False").lower() in ("true", "1", "t")

# Database / Supabase configurations
DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = (
    os.getenv("SUPABASE_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or ""
)
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")

# Payments. No default: card verification and webhooks are refused until this is set.
PAYSTACK_SECRET_KEY: str = os.getenv("PAYSTACK_SECRET_KEY", "").strip()

if not DATABASE_URL:
    raise EnvironmentError("DATABASE_URL was not set or empty in the environment.")

# Frontend (used for links inside emails and CORS)
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://www.novong.com").strip().rstrip("/")

# Outbound email. Resend (HTTPS API) is used when RESEND_API_KEY is set, otherwise SMTP.
# Render's free tier blocks outbound SMTP ports, so prefer Resend there.
MAIL_FROM: str = os.getenv("MAIL_FROM", "info@novong.com").strip()
MAIL_FROM_NAME: str = os.getenv("MAIL_FROM_NAME", "Novo").strip()
MAIL_REPLY_TO: str = os.getenv("MAIL_REPLY_TO", "info@novong.com").strip()
RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "").strip()
SMTP_HOST: str = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "").strip()
# "starttls" (port 587), "ssl" (port 465) or "none"
SMTP_SECURITY: str = os.getenv("SMTP_SECURITY", "starttls").strip().lower()

# Bachs (bachs.io) hosted checkout. Keys look like sk_live_... / sk_sandbox_...; the API base URL
# follows the key type unless BACHS_API_URL is set. Online payment stays off until a key is set.
BACHS_SECRET_KEY: str = os.getenv("BACHS_SECRET_KEY", "").strip()
BACHS_WEBHOOK_SECRET: str = os.getenv("BACHS_WEBHOOK_SECRET", "").strip()
BACHS_API_URL: str = os.getenv("BACHS_API_URL", "").strip()

# Web push (browser/phone notifications). Generate once; the public key is given to browsers.
VAPID_PUBLIC_KEY: str = os.getenv("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY: str = os.getenv("VAPID_PRIVATE_KEY", "").strip()
VAPID_SUBJECT: str = os.getenv("VAPID_SUBJECT", "mailto:info@novong.com").strip()
