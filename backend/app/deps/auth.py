from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Iterable

from fastapi import Cookie, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import User, UserRole
from ..db.session import get_db


class TokenPayload(BaseModel):
    sub: str
    uid: int
    role: UserRole
    type: str
    exp: int
    iss: str
    aud: str


def _create_token(user: User, token_type: str, ttl_seconds: int) -> str:
    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": user.email,
        "uid": user.id,
        "role": user.role.value,
        "type": token_type,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(user: User) -> str:
    return _create_token(user, "access", get_settings().jwt_access_ttl)


def create_refresh_token(user: User) -> str:
    return _create_token(user, "refresh", get_settings().jwt_refresh_ttl)


async def _get_user_from_token(token: str, expected_type: str, db: AsyncSession) -> User:
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
        payload = TokenPayload(**data)
        if payload.type != expected_type:
            raise HTTPException(status_code=401, detail="Invalid token type")
    except JWTError as e:
        raise HTTPException(status_code=401, detail="Invalid token") from e

    res = await db.execute(select(User).where(User.id == payload.uid))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    access_token: Annotated[str | None, Cookie(alias="access_token")]=None,
):
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = await _get_user_from_token(access_token, "access", db)
    request.state.user_id = user.id
    return user


# Role hierarchy: higher index = more privilege
_ROLE_RANK = {
    UserRole.VIEWER: 0,
    UserRole.FIELD_OFFICER: 1,
    UserRole.HOSPITAL_OPS: 2,
    UserRole.EPIDEMIOLOGIST: 3,
    UserRole.ORG_ADMIN: 4,
}


def require_roles(*roles: Iterable[UserRole]) -> Callable:
    """Allow access if user's role is in the list OR has higher privilege than any listed role."""
    min_rank = min(_ROLE_RANK.get(r, 0) for r in roles)

    async def _dep(user: Annotated[User, Depends(get_current_user)]):
        user_rank = _ROLE_RANK.get(user.role, -1)
        if user.role not in roles and user_rank < min_rank:
            raise HTTPException(status_code=403, detail="Forbidden")
        return user

    return _dep


async def csrf_protect(
    request: Request,
    csrf_cookie: Annotated[str | None, Cookie(alias="csrf_token")]=None,
):
    if request.method in {"POST", "PATCH", "DELETE"}:
        header_token = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or not header_token or header_token != csrf_cookie:
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid")

