import pytest
from httpx import AsyncClient

from backend.app.main import app
from backend.app.workers.tasks_models import run_daily_forecasts


@pytest.mark.asyncio
async def test_surge_api():
    run_daily_forecasts(horizon_days=7, target="all")
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        rr = await client.get("/api/v1/regions", cookies=cookies)
        region_id = rr.json()[0]["id"]
        res = await client.get(f"/api/v1/hospital/surge?regionId={region_id}&horizon=7d", cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert "forecast" in data and isinstance(data["forecast"], list) and len(data["forecast"]) >= 1

