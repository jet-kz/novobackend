import asyncio

from fastapi import APIRouter, Body, status, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.mailer import mail_enabled
from app.modules.auth.schemas import UserSignup, UserLogin, UserVerify, ResendCode, ForgotPassword, ResetPassword
from app.modules.auth.service import AuthService, UNVERIFIED_LOGIN_MSG
from app.modules.users.service import UserProfileService
from app.core.security import get_current_user, primary_role
from app.core.database import get_db

router = APIRouter()

def _signup_response(result):
    if isinstance(result, dict):
        return {
            "message": result.get("message") or "User registered successfully",
            "access_token": result.get("access_token"),
            "token_type": "bearer" if result.get("access_token") else None,
            "user": {
                "id": result.get("user_id"),
                "email": result.get("email"),
            },
        }
    session = getattr(result, "session", None)
    access_token = session.access_token if session else None
    return {
        "message": "User registered successfully",
        "access_token": access_token,
        "token_type": "bearer" if access_token else None,
        "user": {
            "id": result.user.id if getattr(result, "user", None) else None,
            "email": result.user.email if getattr(result, "user", None) else None,
        },
    }


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: UserSignup, db: AsyncSession = Depends(get_db)):
    result = await AuthService.sign_up(db, payload)
    response = _signup_response(result)
    response["requires_verification"] = bool(result.get("requires_verification"))
    user_id = (response.get("user") or {}).get("id")
    if user_id:
        try:
            await AuthService.provision_user(db, str(user_id), payload)
        except Exception as exc:
            print(f"Failed to provision user role/profile: {exc}")
    return response


@router.post("/login")
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    try:
        result = await asyncio.to_thread(AuthService.log_in, payload)
    except HTTPException as exc:
        if exc.detail == UNVERIFIED_LOGIN_MSG and mail_enabled():
            # Unverified account: send a fresh code so the client can go straight to the code step.
            await AuthService.send_code(db, payload.email.lower(), "signup")
            raise HTTPException(
                status_code=exc.status_code,
                detail=f"Please verify your email. We've sent a 6-digit code to {payload.email}.",
            )
        raise
    return {
        "access_token": result.get("access_token"),
        "token_type": "bearer",
        "user": {
            "id": result.get("user_id"),
            "email": result.get("email"),
        },
    }


@router.post("/verify-otp")
async def verify_otp(payload: UserVerify, db: AsyncSession = Depends(get_db)):
    result = await AuthService.verify_signup(db, payload)
    access_token = result.get("access_token")
    return {
        "message": "Email verified successfully",
        "access_token": access_token,
        "token_type": "bearer" if access_token else None,
        "user": {"id": result.get("user_id"), "email": result.get("email")},
    }


@router.post("/resend-otp")
async def resend_otp(payload: ResendCode, db: AsyncSession = Depends(get_db)):
    if payload.purpose == "reset":
        return await AuthService.forgot_password(db, payload.email)
    return await AuthService.resend_signup_code(db, payload.email)


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPassword, db: AsyncSession = Depends(get_db)):
    return await AuthService.forgot_password(db, payload.email)


@router.post("/reset-password")
async def reset_password(payload: ResetPassword, db: AsyncSession = Depends(get_db)):
    result = await AuthService.reset_password(db, payload)
    return {**result, "token_type": "bearer" if result.get("access_token") else None}


@router.get("/me")
async def get_current_user_details(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await UserProfileService.get_or_create_profile(db, current_user["user_id"])
    roles = current_user.get("roles") or ["customer"]
    role = primary_role(roles)
    return {
        "message": "Authenticated Successfully",
        "id": current_user.get("user_id"),
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "full_name": profile.full_name,
        "phone": profile.phone,
        "avatar": profile.avatar_url,
        "roles": roles,
        "role": role,
    }


@router.post("/change-password")
async def change_password(payload: dict = Body(...), current_user: dict = Depends(get_current_user)):
    """Signed-in user changes their password. Requires the current one."""
    from app.integrations.supabase.client import supabase, session_client
    from app.modules.notifications import service as notify

    current = str(payload.get("current_password") or "")
    new = str(payload.get("new_password") or "")
    if len(new) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use at least 8 characters for the new password")
    if new == current:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The new password must be different")
    try:
        await asyncio.to_thread(session_client().auth.sign_in_with_password, {"email": current_user.get("email"), "password": current})
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Your current password is incorrect")
    await asyncio.to_thread(supabase.auth.admin.update_user_by_id, current_user["user_id"], {"password": new})
    notify.password_changed(current_user["user_id"])
    return {"success": True, "message": "Password changed", "data": None}
