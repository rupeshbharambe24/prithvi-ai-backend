import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_governance_audit_shape():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        res = await client.get("/api/v1/governance/audit", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert "items" in data and isinstance(data["items"], list)
        if data["items"]:
            item = data["items"][0]
            assert item.get("redacted", False) is True

