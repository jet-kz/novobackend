from supabase import create_client, Client, ClientOptions # type: ignore
from app.core import config

key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_KEY
if not config.SUPABASE_URL or not key:
    raise EnvironmentError(
        "Supabase credentials not configured. Please define SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env"
    )

# Shared service-role client for admin auth calls and storage. Never sign users in on it:
# a sign-in swaps its Authorization header (admin API included) for the user's JWT.
supabase: Client = create_client(config.SUPABASE_URL, key)


def session_client() -> Client:
    """Throwaway client for user-session calls (sign in, sign up, verify OTP)."""
    return create_client(
        config.SUPABASE_URL,
        key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
