from supabase import create_client, Client # type: ignore
from app.core import config

if not config.SUPABASE_URL or not config.SUPABASE_KEY:
    raise EnvironmentError(
        "Supabase credentials not configured. Please define SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env"
    )

supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
