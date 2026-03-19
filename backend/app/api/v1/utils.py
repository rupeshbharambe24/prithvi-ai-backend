from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import _get_user_from_token
from ...db.session import get_db


async def user_from_refresh_cookie(
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias="refresh_token"),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    user = await _get_user_from_token(refresh_token, "refresh", db)
    return user

