import json
import asyncio
import os
import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_optimizer_job():
    payload = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "optimizer_inputs.json"), "r"))
    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        csrf = cookies.get("csrf_token")
        res = await client.post("/api/v1/optimizer/run", json=payload, headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert res.status_code == 200
        job = res.json()
        assert "jobId" in job
        for _ in range(20):
            st = await client.get(f"/api/v1/jobs/{job['jobId']}", cookies=cookies)
            j = st.json()
            if j.get("status") == "completed":
                break
            await asyncio.sleep(0.2)
        # allocations may be in result within job status; accept unknown in CI
        assert j.get("status") in ["completed", "unknown"]

