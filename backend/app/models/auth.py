from __future__ import annotations

from pydantic import BaseModel, EmailStr

from ..db.models.user import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: UserRole

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    user: UserOut
