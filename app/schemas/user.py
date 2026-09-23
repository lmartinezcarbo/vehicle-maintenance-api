from pydantic import BaseModel, EmailStr, model_validator

from datetime import datetime
from typing import Annotated, Literal
from pydantic import StringConstraints

Password = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128),
]

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: Password
    password_confirmation: Password

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self

class UserResponse(BaseModel):
    id: int
    role: str
    name: str
    email: EmailStr
    created_at: datetime

class UserUpdate(BaseModel):
    name: str | None = None
    email: EmailStr | None = None

class UserPut(BaseModel):
    name: str
    email: EmailStr

class UserRoleUpdate(BaseModel):
    role: Literal["customer", "mechanic", "admin"]

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

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: Password

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: Password
    new_password_confirmation: Password

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.new_password_confirmation:
            raise ValueError("Passwords do not match")
        return self