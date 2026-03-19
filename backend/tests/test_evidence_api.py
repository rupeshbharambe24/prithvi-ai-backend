import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_evidence_api_cards():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        # Ensure imported
        await client.post("/api/v1/kg/import", cookies=cookies)
        res = await client.get("/api/v1/evidence?riskId=2", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert "items" in data
        items = data["items"]
        if items:
            assert "summaryMd" in items[0]

