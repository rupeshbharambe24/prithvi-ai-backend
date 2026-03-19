from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps import csrf_protect, rate_limiter_dep
from ...config import get_settings
from ...deps.auth import get_current_user
from ...models.auth import LoginRequest, LoginResponse, SignupRequest, UserOut
from ...services.auth_service import authenticate_user, create_user, issue_tokens
from ...db.session import get_db
from ...utils.crypto import generate_csrf_token


router = APIRouter(prefix="/auth", tags=["auth"])


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    # Local mode uses plain localhost HTTP, so cookies cannot be Secure.
    settings = get_settings()
    if settings.local_mode:
        secure = False
        samesite = "lax"
    elif settings.env == "development":
        secure = True
        samesite = "none"
    else:
        secure = settings.cookie_secure
        samesite = "lax"

    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
    )
    response.set_cookie(
        key="csrf_token",
        value=generate_csrf_token(),
        httponly=False,
        secure=secure,
        samesite=samesite,
        path="/",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(rate_limiter_dep(get_settings().auth_rate_limit_per_minute))],
)
async def login(payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, payload.email, payload.password)
    access, refresh = issue_tokens(user)
    set_auth_cookies(response, access, refresh)
    return LoginResponse(user=UserOut.model_validate(user))


@router.post("/signup", response_model=LoginResponse)
async def signup(payload: SignupRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await create_user(db, payload.email, payload.password)
    access, refresh = issue_tokens(user)
    set_auth_cookies(response, access, refresh)
    return LoginResponse(user=UserOut.model_validate(user))


@router.post("/refresh", dependencies=[Depends(csrf_protect)])
async def refresh(response: Response, db: AsyncSession = Depends(get_db)):
    # We validate refresh token against DB user within dependency on-demand
    from ..v1.utils import user_from_refresh_cookie

    user = await user_from_refresh_cookie(db)
    access, refresh_token = issue_tokens(user)
    set_auth_cookies(response, access, refresh_token)
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(csrf_protect)])
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user=Depends(get_current_user)):
    return UserOut.model_validate(user)
