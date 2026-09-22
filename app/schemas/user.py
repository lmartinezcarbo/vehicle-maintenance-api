from pydantic import BaseModel, EmailStr

from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    role: str
    name: str
    email: EmailStr
    created_at: datetime

class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None
    password: str | None = None

class UserPut(BaseModel):
    name: str
    email: EmailStr
    password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class EmailVerificationRequest(BaseModel):
    email: EmailStr
    code: str

class TwoFactorVerificationRequest(BaseModel):
    email: EmailStr
    code: str

class ResendTwoFactorRequest(BaseModel):
    email: EmailStr

class ResendVerificationRequest(BaseModel):
    email: EmailStr