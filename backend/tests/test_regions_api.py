import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_regions_api():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login as viewer
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        res = await client.get("/api/v1/regions", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list) and len(data) >= 3
        item = data[0]
        assert set(["id", "code", "name", "center", "bounds"]).issubset(item.keys())
        assert isinstance(item["center"], dict) and "lat" in item["center"] and "lng" in item["center"]
        assert isinstance(item["bounds"], list)

