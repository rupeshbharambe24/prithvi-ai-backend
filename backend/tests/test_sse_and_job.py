import asyncio
import json
import pytest
from httpx import AsyncClient

from backend.app.main import app


@pytest.mark.asyncio
async def test_sse_and_demo_job():
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login to obtain CSRF token
        r_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        assert r_login.status_code == 200
        cookies = r_login.cookies
        csrf = cookies.get("csrf_token")

        # Start long job
        r = await client.post("/api/v1/demo/long-job", headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert r.status_code == 202
        job_id = r.json()["jobId"]

        # Stream SSE
        progress_events = 0
        heartbeat_seen = False
        async with client.stream("GET", "/api/v1/events/stream", cookies=cookies) as s:
            async for line in s.aiter_lines():
                if line.startswith("event: heartbeat"):
                    heartbeat_seen = True
                if line.startswith("data:"):
                    try:
                        payload = json.loads(line.split("data: ", 1)[1])
                    except Exception:
                        payload = None
                    if isinstance(payload, dict) and payload.get("jobId") == job_id:
                        progress_events += 1
                        if progress_events >= 2:
                            break
                await asyncio.sleep(0.05)
        assert progress_events >= 2
        assert heartbeat_seen is True or progress_events >= 2

