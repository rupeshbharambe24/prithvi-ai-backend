from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Org, User, UserRole
from ..utils.crypto import hash_password, verify_password
from ..deps.auth import create_access_token, create_refresh_token


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    res = await db.execute(select(User).where(User.email == email))
    user = res.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def issue_tokens(user: User) -> tuple[str, str]:
    return create_access_token(user), create_refresh_token(user)


async def create_user(db: AsyncSession, email: str, password: str) -> User:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    org = (await db.execute(select(Org).where(Org.name == "Demo Health Dept"))).scalar_one_or_none()
    if org is None:
        org = Org(name="Demo Health Dept")
        db.add(org)
        await db.flush()
    user = User(
        email=email,
        password_hash=hash_password(password),
        role=UserRole.VIEWER,
        org_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
