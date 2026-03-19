import asyncio
import re

import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_auth_login_and_me():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Without cookie, /me returns 401
        r = await client.get("/api/v1/auth/me")
        assert r.status_code == 401

        # Login
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        assert r.status_code == 200
        set_cookie = r.headers.get("set-cookie", "")
        assert "access_token=" in set_cookie

        # Use returned cookies to call /me
        cookies = r.cookies
        r2 = await client.get("/api/v1/auth/me", cookies=cookies)
        assert r2.status_code == 200
        data = r2.json()
        assert data["email"] == "admin@example.com"


@pytest.mark.asyncio
async def test_rbac_guard():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login as viewer
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        assert r.status_code == 200
        cookies = r.cookies
        # viewer forbidden on admin route
        r2 = await client.get("/api/v1/admin/ping", cookies=cookies)
        assert r2.status_code == 403

