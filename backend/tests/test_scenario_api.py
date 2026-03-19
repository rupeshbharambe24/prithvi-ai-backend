import json
import asyncio
import os
import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_scenario_sync_and_job():
    payload = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "scenario_input.json"), "r"))
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        csrf = cookies.get("csrf_token")
        # Sync
        res = await client.post("/api/v1/scenario/run", json=payload, headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert res.status_code == 200
        data = res.json()
        assert "delta" in data and "ci" in data and data["ci"][0] <= data["ci"][1]
        # Job
        res2 = await client.post("/api/v1/scenario/run/job", json=payload, headers={"X-CSRF-Token": csrf}, cookies=cookies)
        job = res2.json()
        assert "jobId" in job
        # Poll jobs API
        for _ in range(20):
            st = await client.get(f"/api/v1/jobs/{job['jobId']}", cookies=cookies)
            js = st.json()
            if js.get("status") == "completed":
                break
            await asyncio.sleep(0.2)
        assert js.get("status") in ["completed", "unknown"]

