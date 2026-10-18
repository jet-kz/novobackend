from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import urllib.request
import json
import threading

from app.core import config
from app.core.database import get_db
from app.modules.auth.models import Role, UserRole

security = HTTPBearer(auto_error=False)

SUPABASE_JWT_SECRET = config.SUPABASE_JWT_SECRET
SUPABASE_URL = config.SUPABASE_URL

_JWKS_CACHE = None
_JWKS_LOCK = threading.Lock()

INVALID_TOKENS = ("demo-token", "mock-jwt-token", "undefined", "null", "")

DEV_FALLBACK_USER = {
    "user_id": "00000000-0000-0000-0000-000000000001",
    "email": "customer@novo.com",
    "roles": ["customer"],
    "raw_payload": {},
}


def primary_role(roles: list | None) -> str:
    roles = roles or []
    if "super_admin" in roles or "admin" in roles:
        return "admin"
    if "merchant_owner" in roles:
        return "merchant"
    if "rider" in roles:
        return "rider"
    return "customer"


def get_jwks():
    global _JWKS_CACHE
    if _JWKS_CACHE is not None:
        return _JWKS_CACHE

    with _JWKS_LOCK:
        if _JWKS_CACHE is not None:
            return _JWKS_CACHE
        try:
            jwks_url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            with urllib.request.urlopen(jwks_url, timeout=5) as response:
                _JWKS_CACHE = json.loads(response.read().decode("utf-8"))
            return _JWKS_CACHE
        except Exception as e:
            print(f"Error fetching Supabase JWKS: {e}")
            return None


def decode_supabase_jwt(token: str) -> dict:
    try:
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "HS256")

        if alg == "ES256":
            jwks = get_jwks()
            if jwks is None:
                raise JWTError("JWKS key set not available")
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["ES256"],
                audience="authenticated",
            )
        else:
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate Supabase credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _unauthorized(detail: str = "Not authenticated"):
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a Supabase JWT and attach Novo roles from user_roles.
    Unauthenticated or invalid tokens are rejected unless ALLOW_INSECURE_DEV_AUTH is set.
    """
    if not credentials or not credentials.credentials or credentials.credentials in INVALID_TOKENS:
        if config.ALLOW_INSECURE_DEV_AUTH:
            return DEV_FALLBACK_USER
        _unauthorized()

    token = credentials.credentials
    try:
        payload = decode_supabase_jwt(token)
        user_id = payload.get("sub")
        if not user_id:
            _unauthorized("Token is missing a subject")

        stmt = select(Role.name).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user_id)
        result = await db.execute(stmt)
        roles = list(result.scalars().all())

        # Suspended accounts lose access immediately, even with a token that hasn't expired yet.
        from app.modules.users.models import UserProfile

        active = (await db.execute(select(UserProfile.is_active).where(UserProfile.user_id == user_id))).scalar_one_or_none()
        if active is False:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This account has been suspended. Contact info@novong.com.")
        if not roles:
            roles = ["customer"]

        return {
            "user_id": user_id,
            "email": payload.get("email"),
            "roles": roles,
            "raw_payload": payload,
        }
    except HTTPException:
        if config.ALLOW_INSECURE_DEV_AUTH:
            return DEV_FALLBACK_USER
        raise
    except Exception:
        if config.ALLOW_INSECURE_DEV_AUTH:
            return DEV_FALLBACK_USER
        _unauthorized("Could not validate credentials")


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    """The signed-in user, or None for guests (including a stale/expired token left in the browser)."""
    if not credentials or not credentials.credentials or credentials.credentials in INVALID_TOKENS:
        return None
    try:
        user = await get_current_user(credentials, db)
    except HTTPException:
        return None
    return None if user is DEV_FALLBACK_USER else user


def require_role(required_role: str):
    def role_verifier(current_user: dict = Depends(get_current_user)):
        roles = current_user.get("roles") or []
        if "super_admin" in roles:
            return current_user
        if required_role == "admin" and "admin" in roles:
            return current_user
        if required_role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires role: {required_role}",
            )
        return current_user

    return role_verifier
