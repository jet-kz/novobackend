from fastapi import APIRouter, status, Depends
from app.modules.auth.schemas import UserSignup, UserLogin, UserVerify
from app.modules.auth.service import AuthService
from app.core.security import get_current_user

router = APIRouter()

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: UserSignup):
    result = AuthService.sign_up(payload)
    if isinstance(result, dict):
        return {
            "message": "User registered successfully",
            "access_token": result.get("access_token"),
            "token_type": "bearer",
            "user": {
                "id": result.get("user_id"),
                "email": result.get("email")
            }
        }
    session = getattr(result, "session", None)
    access_token = session.access_token if session else None
    return {
        "message": "User registered successfully",
        "access_token": access_token,
        "token_type": "bearer" if access_token else None,
        "user": {
            "id": result.user.id if getattr(result, "user", None) else None,
            "email": result.user.email if getattr(result, "user", None) else None
        }
    }

@router.post("/login")
def login(payload: UserLogin):
    result = AuthService.log_in(payload)
    if isinstance(result, dict):
        return {
            "access_token": result.get("access_token"),
            "token_type": "bearer",
            "user": {
                "id": result.get("user_id"),
                "email": result.get("email")
            }
        }
    return {
        "access_token": result.session.access_token,
        "token_type": "bearer",
        "user": {
            "id": result.user.id if getattr(result, "user", None) else None,
            "email": result.user.email if getattr(result, "user", None) else None
        }
    }

@router.post("/verify-otp")
def verify_otp(payload: UserVerify):
    result = AuthService.verify_otp(payload)
    return {
        "message": "OTP Verified Successfully",
        "access_token": result.session.access_token if result.session else None,
        "token_type": "bearer"
    }

@router.get("/me")
def get_current_user_details(current_user: dict = Depends(get_current_user)):
    """
    Test endpoint for validating the Supabase JWT and extracting standard roles.
    """
    return {
        "message": "Authenticated Successfully",
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "roles": current_user.get("roles")
    }
