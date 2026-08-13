from app.integrations.supabase.client import supabase
from app.modules.auth.schemas import UserSignup, UserLogin, UserVerify
from fastapi import HTTPException, status

class AuthService:
    @staticmethod
    def sign_up(user_schema: UserSignup):
        try:
            result = supabase.auth.sign_up({
                "email": user_schema.email,
                "password": user_schema.password
            })
            return result
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Registration failed: {str(e)}"
            )

    @staticmethod
    def log_in(user_schema: UserLogin):
        try:
            result = supabase.auth.sign_in_with_password({
                "email": user_schema.email,
                "password": user_schema.password
            })
            return result
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Login failed: {str(e)}"
            )

    @staticmethod
    def verify_otp(payload: UserVerify):
        try:
            result = supabase.auth.verify_otp({
                "email": payload.email,
                "token": payload.token,
                "type": "signup"
            })
            return result
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OTP Verification failed: {str(e)}"
            )
