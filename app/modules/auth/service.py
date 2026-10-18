import asyncio
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core import config
from app.core.mailer import mail_enabled, send_email
from app.integrations.supabase.client import supabase, session_client
from app.modules.auth.schemas import UserSignup, UserLogin, UserVerify, ResetPassword
from app.modules.auth.models import EmailCode, Role, UserRole
from app.modules.notifications import service as notify
from app.modules.notifications import templates
from app.modules.users.models import UserProfile
from fastapi import HTTPException, status

logger = logging.getLogger("novo.auth")

ALLOWED_SELF_ASSIGN_ROLES = {"customer", "merchant_owner", "rider"}

SIGNUP_ROLE_ALIASES = {
    "customer": "customer",
    "merchant": "merchant_owner",
    "merchant_owner": "merchant_owner",
    "rider": "rider",
}

CODE_TTL_MINUTES = 15
CODE_MAX_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 45
UNVERIFIED_LOGIN_MSG = "Please verify your email before logging in."


@dataclass
class AuthUser:
    id: str
    email: str
    confirmed: bool
    full_name: str | None


def _hash_code(email: str, purpose: str, code: str) -> str:
    key = (config.SUPABASE_JWT_SECRET or "novo-email-codes").encode()
    return hmac.new(key, f"{email}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()


class AuthService:
    # ── Lookups ──────────────────────────────────────────────────────────────

    @staticmethod
    async def find_user(db: AsyncSession, email: str) -> AuthUser | None:
        row = (await db.execute(
            text(
                "select u.id::text, u.email, u.email_confirmed_at is not null, "
                "coalesce(p.full_name, u.raw_user_meta_data->>'full_name') "
                "from auth.users u left join user_profiles p on p.user_id = u.id::text "
                "where lower(u.email) = lower(:email) and u.deleted_at is null limit 1"
            ),
            {"email": email},
        )).first()
        return AuthUser(*row) if row else None

    @staticmethod
    async def signup_role(db: AsyncSession, user_id: str) -> str:
        res = await db.execute(
            select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        )
        names = set(res.scalars().all())
        for role in ("merchant_owner", "rider"):
            if role in names:
                return role
        return "customer"

    # ── One-time codes ───────────────────────────────────────────────────────

    @staticmethod
    async def _issue_code(db: AsyncSession, email: str, purpose: str) -> str | None:
        """New code for (email, purpose), retiring older ones. None while the resend cooldown is active."""
        now = datetime.now(timezone.utc)
        latest = (await db.execute(
            select(EmailCode)
            .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
            .order_by(EmailCode.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest and latest.created_at and (now - latest.created_at).total_seconds() < RESEND_COOLDOWN_SECONDS:
            return None

        await db.execute(
            update(EmailCode)
            .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(EmailCode(
            email=email,
            purpose=purpose,
            code_hash=_hash_code(email, purpose, code),
            attempts=0,
            expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
        ))
        await db.commit()
        return code

    @staticmethod
    async def send_code(db: AsyncSession, email: str, purpose: str, name: str | None = None) -> bool:
        """Email a fresh code. Returns False only when sending failed (cooldown counts as sent)."""
        code = await AuthService._issue_code(db, email, purpose)
        if code is None:
            return True
        build = templates.verification_code if purpose == "signup" else templates.password_reset_code
        return await send_email(email, *build(name, code, CODE_TTL_MINUTES))

    @staticmethod
    async def _consume_code(db: AsyncSession, email: str, purpose: str, token: str) -> bool:
        """True if the code matched. False if there is no live code. Raises on a wrong code."""
        now = datetime.now(timezone.utc)
        record = (await db.execute(
            select(EmailCode)
            .where(
                EmailCode.email == email,
                EmailCode.purpose == purpose,
                EmailCode.consumed_at.is_(None),
                EmailCode.expires_at > now,
            )
            .order_by(EmailCode.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not record:
            return False
        if record.attempts >= CODE_MAX_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                detail="Too many incorrect attempts. Request a new code.")
        if not hmac.compare_digest(record.code_hash, _hash_code(email, purpose, token.strip())):
            record.attempts += 1
            await db.commit()
            left = CODE_MAX_ATTEMPTS - record.attempts
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"That code is incorrect. {left} attempt{'s' if left != 1 else ''} left."
                                if left else "Too many incorrect attempts. Request a new code.")
        record.consumed_at = now
        await db.commit()
        return True

    # ── Flows ────────────────────────────────────────────────────────────────

    @staticmethod
    def _password_sign_in(email: str, password: str) -> str | None:
        try:
            result = session_client().auth.sign_in_with_password({"email": email, "password": password})
            return result.session.access_token if getattr(result, "session", None) else None
        except Exception as exc:
            logger.warning("Post-verification sign-in failed for %s: %s", email, exc)
            return None

    @staticmethod
    async def sign_up(db: AsyncSession, user_schema: UserSignup) -> dict:
        email = user_schema.email.lower()
        user_data = {k: v for k, v in {
            "full_name": user_schema.full_name,
            "role": user_schema.role,
            "phone": user_schema.phone,
        }.items() if v}

        if not mail_enabled():
            return await asyncio.to_thread(AuthService._legacy_sign_up, email, user_schema.password, user_data)

        existing = await AuthService.find_user(db, email)
        if existing and existing.confirmed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists. Sign in, or reset your password if you've forgotten it.",
            )
        try:
            if existing:
                # Unverified signup being retried: take the new password and details.
                await asyncio.to_thread(
                    supabase.auth.admin.update_user_by_id,
                    existing.id, {"password": user_schema.password, "user_metadata": user_data},
                )
                user_id = existing.id
            else:
                created = await asyncio.to_thread(supabase.auth.admin.create_user, {
                    "email": email,
                    "password": user_schema.password,
                    "email_confirm": False,
                    "user_metadata": user_data,
                })
                user_id = created.user.id
        except Exception as e:
            logger.exception("Supabase user creation failed for %s", email)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Registration failed: {e}")

        sent = await AuthService.send_code(db, email, "signup", user_schema.full_name)
        return {
            "access_token": None,
            "user_id": str(user_id),
            "email": email,
            "requires_verification": True,
            "message": f"We've sent a 6-digit code to {email}." if sent
            else "Account created, but we couldn't send the code. Tap 'Resend code' to try again.",
        }

    @staticmethod
    def _legacy_sign_up(email: str, password: str, user_data: dict) -> dict:
        """Supabase sends the confirmation email itself. Used when no mail provider is configured."""
        try:
            payload = {"email": email, "password": password}
            if user_data:
                payload["options"] = {"data": user_data}
            result = session_client().auth.sign_up(payload)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Registration failed: {e}")
        user_id = getattr(result.user, "id", None) if getattr(result, "user", None) else None
        access_token = getattr(result.session, "access_token", None) if getattr(result, "session", None) else None
        return {
            "access_token": access_token,
            "user_id": user_id,
            "email": email,
            "requires_verification": not access_token,
            "message": "User registered successfully." if access_token else f"We've sent a verification code to {email}.",
        }

    @staticmethod
    def log_in(user_schema: UserLogin):
        try:
            result = session_client().auth.sign_in_with_password({
                "email": user_schema.email,
                "password": user_schema.password
            })
            if getattr(result, "session", None) and getattr(result.session, "access_token", None):
                return {
                    "access_token": result.session.access_token,
                    "token_type": "bearer",
                    "user_id": result.user.id if getattr(result, "user", None) else "",
                    "email": user_schema.email
                }
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials. Session token not returned by Supabase Auth."
            )
        except HTTPException:
            raise
        except Exception as e:
            err = str(e).lower()
            code = status.HTTP_401_UNAUTHORIZED
            if "invalid login credentials" in err or "invalid password" in err:
                msg = "Incorrect email or password. Please try again."
            elif "user not found" in err or "no user found" in err:
                msg = "No account found with this email address."
            elif "email not confirmed" in err:
                msg, code = UNVERIFIED_LOGIN_MSG, status.HTTP_403_FORBIDDEN
            elif "too many requests" in err:
                msg = "Too many login attempts. Please wait a moment and try again."
            elif "name or service not known" in err or "connection" in err:
                msg = "Service temporarily unavailable. Please try again shortly."
            else:
                msg = "Login failed. Please check your credentials and try again."
            raise HTTPException(status_code=code, detail=msg)

    @staticmethod
    async def verify_signup(db: AsyncSession, payload: UserVerify) -> dict:
        email = payload.email.lower()
        if not await AuthService._consume_code(db, email, "signup", payload.token):
            if mail_enabled():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="This code has expired. Request a new one.")
            return await asyncio.to_thread(AuthService._legacy_verify, email, payload.token, "signup")

        user = await AuthService.find_user(db, email)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account found for this email.")
        if not user.confirmed:
            await asyncio.to_thread(supabase.auth.admin.update_user_by_id, user.id, {"email_confirm": True})
            notify.welcome(user.id, await AuthService.signup_role(db, user.id))

        access_token = None
        if payload.password:
            access_token = await asyncio.to_thread(AuthService._password_sign_in, email, payload.password)
        return {"access_token": access_token, "user_id": user.id, "email": email}

    @staticmethod
    def _legacy_verify(email: str, token: str, otp_type: str) -> dict:
        try:
            result = session_client().auth.verify_otp({"email": email, "token": token.strip(), "type": otp_type})
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Verification failed: {e}")
        access_token = getattr(result.session, "access_token", None) if getattr(result, "session", None) else None
        user_id = getattr(result.user, "id", None) if getattr(result, "user", None) else None
        return {"access_token": access_token, "user_id": user_id, "email": email}

    @staticmethod
    async def resend_signup_code(db: AsyncSession, email: str) -> dict:
        email = email.lower()
        user = await AuthService.find_user(db, email)
        if user and user.confirmed:
            return {"message": "This email is already verified. You can sign in."}
        if user:
            if mail_enabled():
                code = await AuthService._issue_code(db, email, "signup")
                if code is None:
                    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                                        detail=f"Please wait {RESEND_COOLDOWN_SECONDS} seconds before requesting another code.")
                await send_email(email, *templates.verification_code(user.full_name, code, CODE_TTL_MINUTES))
            else:
                try:
                    await asyncio.to_thread(session_client().auth.resend, {"type": "signup", "email": email})
                except Exception as e:
                    logger.warning("Supabase resend failed for %s: %s", email, e)
        return {"message": f"If {email} has an unverified account, a new code is on its way."}

    @staticmethod
    async def forgot_password(db: AsyncSession, email: str) -> dict:
        email = email.lower()
        user = await AuthService.find_user(db, email)
        if user:
            if mail_enabled():
                await AuthService.send_code(db, email, "reset", user.full_name)
            else:
                try:
                    await asyncio.to_thread(session_client().auth.reset_password_for_email, email)
                except Exception as e:
                    logger.warning("Supabase reset email failed for %s: %s", email, e)
        # Same answer whether or not the account exists.
        return {"message": f"If an account exists for {email}, we've sent a 6-digit reset code."}

    @staticmethod
    async def reset_password(db: AsyncSession, payload: ResetPassword) -> dict:
        email = payload.email.lower()
        if await AuthService._consume_code(db, email, "reset", payload.token):
            user = await AuthService.find_user(db, email)
            user_id = user.id if user else None
        elif not mail_enabled():
            user_id = (await asyncio.to_thread(AuthService._legacy_verify, email, payload.token, "recovery")).get("user_id")
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This code has expired. Request a new one.")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account found for this email.")

        try:
            # Entering the emailed code also proves they own the address.
            await asyncio.to_thread(
                supabase.auth.admin.update_user_by_id,
                str(user_id), {"password": payload.new_password, "email_confirm": True},
            )
        except Exception as e:
            logger.exception("Password update failed for %s", email)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not update password: {e}")
        notify.password_changed(str(user_id))

        access_token = await asyncio.to_thread(AuthService._password_sign_in, email, payload.new_password)
        return {"message": "Your password has been reset.", "access_token": access_token, "email": email}

    # ── Roles / profile ──────────────────────────────────────────────────────

    @staticmethod
    def resolve_signup_role(requested: str | None) -> str:
        key = (requested or "customer").strip().lower()
        mapped = SIGNUP_ROLE_ALIASES.get(key, "customer")
        if mapped not in ALLOWED_SELF_ASSIGN_ROLES:
            return "customer"
        return mapped

    @staticmethod
    async def provision_user(db: AsyncSession, user_id: str, payload: UserSignup):
        if not user_id:
            return
        role_name = AuthService.resolve_signup_role(payload.role)
        role_res = await db.execute(select(Role).where(Role.name == role_name))
        role = role_res.scalar_one_or_none()
        if not role:
            role = Role(id=f"role_{role_name}", name=role_name)
            db.add(role)
            await db.flush()

        existing_role = await db.execute(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        )
        if not existing_role.scalar_one_or_none():
            db.add(UserRole(user_id=user_id, role_id=role.id))

        profile_res = await db.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        profile = profile_res.scalar_one_or_none()
        if not profile:
            db.add(UserProfile(user_id=user_id, full_name=payload.full_name, phone=payload.phone))
        else:
            if payload.full_name:
                profile.full_name = payload.full_name
            if payload.phone:
                profile.phone = payload.phone

        if role_name == "rider":
            from app.modules.riders.service import RiderService

            await RiderService.get_or_create_for_user(
                db, user_id, {"vehicle_type": payload.vehicle_type, "vehicle_plate": payload.vehicle_plate}
            )
        await db.commit()
