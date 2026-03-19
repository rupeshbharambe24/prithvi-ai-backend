import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_disease_api():
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        rr = await client.get("/api/v1/regions", cookies=cookies)
        region_id = rr.json()[0]["id"]
        res = await client.get(f"/api/v1/risk/disease?type=dengue&regionId={region_id}&horizon=28d", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert "series" in data and isinstance(data["series"], list)
        if data["series"]:
            v = data["series"][0]["risk"]
            assert 0.0 <= v <= 1.0

