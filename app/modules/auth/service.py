import uuid
from app.integrations.supabase.client import supabase
from app.modules.auth.schemas import UserSignup, UserLogin, UserVerify
from fastapi import HTTPException, status

class AuthService:
    @staticmethod
    def sign_up(user_schema: UserSignup):
        user_email = user_schema.email

        try:
            signup_payload = {
                "email": user_schema.email,
                "password": user_schema.password
            }
            user_data = {}
            if user_schema.full_name:
                user_data["full_name"] = user_schema.full_name
            if user_schema.role:
                user_data["role"] = user_schema.role
            if user_schema.phone:
                user_data["phone"] = user_schema.phone

            if user_data:
                signup_payload["options"] = {"data": user_data}

            result = supabase.auth.sign_up(signup_payload)
            
            user_id = getattr(result.user, "id", str(uuid.uuid4())) if getattr(result, "user", None) else str(uuid.uuid4())
            access_token = None
            if getattr(result, "session", None) and getattr(result.session, "access_token", None):
                access_token = result.session.access_token

            return {
                "access_token": access_token,
                "token_type": "bearer",
                "user_id": user_id,
                "email": user_email,
                "message": "User registered successfully with Supabase Auth." if access_token else "User registered. Please check email for OTP verification."
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Supabase Registration Error: {str(e)}"
            )

    @staticmethod
    def log_in(user_schema: UserLogin):
        user_email = user_schema.email
        try:
            result = supabase.auth.sign_in_with_password({
                "email": user_schema.email,
                "password": user_schema.password
            })
            if getattr(result, "session", None) and getattr(result.session, "access_token", None):
                return {
                    "access_token": result.session.access_token,
                    "token_type": "bearer",
                    "user_id": result.user.id if getattr(result, "user", None) else "",
                    "email": user_email
                }
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials. Session token not returned by Supabase Auth."
                )
        except HTTPException:
            raise
        except Exception as e:
            err = str(e).lower()
            if "invalid login credentials" in err or "invalid password" in err:
                msg = "Incorrect email or password. Please try again."
            elif "user not found" in err or "no user found" in err:
                msg = "No account found with this email address."
            elif "email not confirmed" in err:
                msg = "Please verify your email before logging in."
            elif "too many requests" in err:
                msg = "Too many login attempts. Please wait a moment and try again."
            elif "name or service not known" in err or "connection" in err:
                msg = "Service temporarily unavailable. Please try again shortly."
            else:
                msg = "Login failed. Please check your credentials and try again."
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=msg)

    @staticmethod
    def verify_otp(payload: UserVerify):
        try:
            result = supabase.auth.verify_otp({
                "email": payload.email,
                "token": payload.token,
                "type": "signup"
            })
            access_token = getattr(result.session, "access_token", None) if getattr(result, "session", None) else None
            return {
                "access_token": access_token,
                "user": getattr(result, "user", None)
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OTP Verification failed: {str(e)}"
            )
