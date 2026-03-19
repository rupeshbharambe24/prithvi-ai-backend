import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_health_ok():
    async with AsyncClient(app=app, base_url="http://test", headers={"X-Forwarded-For": "9.9.9.9"}) as client:
        r = await client.get("/api/v1/health/")
        assert r.status_code == 200
        data = r.json()
        assert data["db"] is True
        assert data["redis"] is True
        assert data["objectStore"] is True
        assert "uptimeSeconds" in data

        # Rate limit: make 61 calls quickly should trigger 429
        too_many = None
        for i in range(61):
            resp = await client.get("/api/v1/health/")
            if resp.status_code == 429:
                too_many = True
                break
        assert too_many is True
