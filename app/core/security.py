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

security = HTTPBearer()

SUPABASE_JWT_SECRET = config.SUPABASE_JWT_SECRET
SUPABASE_URL = config.SUPABASE_URL

# In-memory cache for JWKS keys to avoid high latency on every request
_JWKS_CACHE = None
_JWKS_LOCK = threading.Lock()

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
                _JWKS_CACHE = json.loads(response.read().decode('utf-8'))
            return _JWKS_CACHE
        except Exception as e:
            # Do not persist None if download fails, so we can retry next time
            print(f"Error fetching Supabase JWKS: {e}")
            return None

def decode_supabase_jwt(token: str) -> dict:
    try:
        # Determine algorithm by looking at the unverified header first
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "HS256")
        
        if alg == "ES256":
            # Asymmetric key validation using JWKS
            jwks = get_jwks()
            if jwks is None:
                raise JWTError("JWKS key set not available")
            payload = jwt.decode(
                token, 
                jwks, 
                algorithms=["ES256"], 
                audience="authenticated"
            )
        else:
            # Fallback to symmetric checks if legacy HS256 is used
            payload = jwt.decode(
                token, 
                SUPABASE_JWT_SECRET, 
                algorithms=["HS256"], 
                audience="authenticated"
            )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate Supabase credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """
    Dependency to validate Supabase JWT and inject the authenticated user's ID and custom Novo Roles.
    """
    token = credentials.credentials
    payload = decode_supabase_jwt(token)
    
    # 'sub' contains the auth.users UUID
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT from Supabase auth.",
        )
    
    # Fetch roles mapped to this user in our custom schema
    stmt = select(Role.name).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user_id)
    result = await db.execute(stmt)
    roles = result.scalars().all()

    return {
        "user_id": user_id,
        "email": payload.get("email"),
        "roles": roles, # E.g., ['customer', 'merchant_owner']
        "raw_payload": payload
    }

def require_role(required_role: str):
    """
    Dependency factory to enforce custom role access mapping.
    """
    def role_verifier(current_user: dict = Depends(get_current_user)):
        if "super_admin" in current_user["roles"]:
            return current_user
        if required_role not in current_user["roles"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted. Requires role: {required_role}"
            )
        return current_user
    return role_verifier
