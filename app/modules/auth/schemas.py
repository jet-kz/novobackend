from pydantic import BaseModel, EmailStr, Field

from typing import Literal, Optional

class UserSignup(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = None
    role: Optional[str] = "customer"
    phone: Optional[str] = None
    vehicle_type: Optional[str] = None
    vehicle_plate: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserVerify(BaseModel):
    email: EmailStr
    token: str
    # When given, a verified user is signed in and an access token is returned.
    password: Optional[str] = None

class ResendCode(BaseModel):
    email: EmailStr
    purpose: Literal["signup", "reset"] = "signup"

class ForgotPassword(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    email: EmailStr
    token: str
    new_password: str = Field(..., min_length=6)
