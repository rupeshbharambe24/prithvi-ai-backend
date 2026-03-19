import asyncio
import pytest
from httpx import AsyncClient

from backend.app.main import app
from backend.app.workers.tasks_models import run_daily_forecasts


@pytest.mark.asyncio
async def test_alerts_engine_and_sse():
    # Ensure forecasts exist
    run_daily_forecasts(horizon_days=3, target="heat")
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Login as admin
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin123!"},
        )
        cookies = r.cookies
        csrf = cookies.get("csrf_token")
        # Create rule
        rule = {
            "name": "Heat >= 0.2",
            "metric": "risk.heat",
            "regionFilter": "*",
            "condition": ">=",
            "threshold": 0.2,
            "horizonDays": 3,
            "severity": "warn",
            "channels": ["email"],
            "cooldownMinutes": 60
        }
        await client.post("/api/v1/alerts/rules", json=rule, headers={"X-CSRF-Token": csrf}, cookies=cookies)

        # Open SSE stream
        async with client.stream("GET", "/api/v1/events/stream", cookies=cookies) as sse:
            # Trigger evaluation
            run = await client.post("/api/v1/alerts/run", headers={"X-CSRF-Token": csrf}, cookies=cookies)
            assert run.status_code == 200
            created_seen = False
            async for line in sse.aiter_lines():
                if line.startswith("event: alert-created"):
                    created_seen = True
                    break
                await asyncio.sleep(0.1)
        assert created_seen

        # List alerts
        res = await client.get("/api/v1/alerts?status=open", cookies=cookies)
        assert res.status_code == 200
        items = res.json()
        assert len(items) >= 1
        aid = items[0]["id"]
        # Ack
        res2 = await client.patch(f"/api/v1/alerts/{aid}", json={"status": "ack"}, headers={"X-CSRF-Token": csrf}, cookies=cookies)
        assert res2.status_code == 200

