from supabase import create_client, Client # type: ignore
from app.core import config

key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_KEY
if not config.SUPABASE_URL or not key:
    raise EnvironmentError(
        "Supabase credentials not configured. Please define SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env"
    )

supabase: Client = create_client(config.SUPABASE_URL, key)
