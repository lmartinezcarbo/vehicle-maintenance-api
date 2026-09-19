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

class UserLogin(BaseModel):
    email: EmailStr
    password: str