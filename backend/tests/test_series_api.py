import time
import pytest
from httpx import AsyncClient
from datetime import datetime, timezone

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.etl.era5 import flow_era5_ingest


@pytest.mark.asyncio
async def test_series_api_and_cache():
    # ensure data exists
    async with AsyncSessionLocal() as db:
        await flow_era5_ingest(db, datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 7, 3, tzinfo=timezone.utc))

    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        # Get a region id
        rr = await client.get("/api/v1/regions", cookies=cookies)
        region_id = rr.json()[0]["id"]
        url = f"/api/v1/data/series?regionId={region_id}&key=heat_index&from=2024-07-01&to=2024-07-03"
        t0 = time.perf_counter()
        res1 = await client.get(url, cookies=cookies)
        t1 = time.perf_counter() - t0
        assert res1.status_code == 200
        data = res1.json()
        assert "points" in data and isinstance(data["points"], list)
        assert "meta" in data and data["meta"]["featureKey"] == "heat_index"
        # cached
        t0 = time.perf_counter()
        res2 = await client.get(url, cookies=cookies)
        t2 = time.perf_counter() - t0
        assert res2.status_code == 200
        assert t2 <= t1
        # Quality endpoint shape
        # Use dataset id 1 as a fallback; this checks shape primarily
        q = await client.get("/api/v1/data/quality?datasetId=1", cookies=cookies)
        assert q.status_code == 200
        qd = q.json()
        assert "issues" in qd and "lastRun" in qd

