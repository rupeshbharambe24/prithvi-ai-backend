import time
import pytest
from httpx import AsyncClient

from backend.app.main import app
from backend.app.workers.tasks_models import run_daily_forecasts


@pytest.mark.asyncio
async def test_heat_api_contract_and_latency():
    run_daily_forecasts(horizon_days=7, target="heat")
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        rr = await client.get("/api/v1/regions", cookies=cookies)
        region_id = rr.json()[0]["id"]
        url = f"/api/v1/risk/heat?regionId={region_id}&horizon=7d"
        # prime
        await client.get(url, cookies=cookies)
        t0 = time.perf_counter()
        res = await client.get(url, cookies=cookies)
        dt = time.perf_counter() - t0
        assert res.status_code == 200
        data = res.json()
        assert "series" in data and isinstance(data["series"], list) and len(data["series"]) >= 1
        assert "drivers" in data and isinstance(data["drivers"], list)
        item = data["series"][0]
        assert set(["date", "risk", "p05", "p95"]).issubset(item.keys())
        assert dt < 0.5  # warm latency under 500ms

