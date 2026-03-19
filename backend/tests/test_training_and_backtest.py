import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal
from backend.app.workers.tasks_models import train_models, run_daily_forecasts, run_backtests


@pytest.mark.asyncio
async def test_training_forecasts_backtest_and_registry():
    # Train models for heat
    out = train_models("heat")
    assert isinstance(out, dict)

    # Verify registry entries exist and artifacts saved
    async with AsyncSessionLocal() as db:
        mv_rows = (await db.execute(text("SELECT id, path, metrics_json FROM model_versions WHERE target='heat'"))).fetchall()
        assert len(mv_rows) >= 2
        for _, path, metrics in mv_rows:
            assert path and os.path.exists(path)
            assert metrics is None or isinstance(metrics, dict) or isinstance(metrics, str)

    # Forecast 7 days for all targets to populate tables
    res = run_daily_forecasts(horizon_days=7, target="all")
    assert isinstance(res, dict) and res.get("rows", 0) >= 7

    # Check forecasts written and validity bounds
    async with AsyncSessionLocal() as db:
        rid = (await db.execute(text("SELECT id FROM regions LIMIT 1"))).scalar()
        today = datetime.now(timezone.utc).date()
        rows = (await db.execute(text("""
            SELECT value, p05, p95, drivers_json FROM forecasts
            WHERE region_id=:rid AND type='heat' AND target_date >= :today
            ORDER BY target_date ASC
        """), {"rid": rid, "today": datetime(today.year, today.month, today.day, tzinfo=timezone.utc)})).fetchall()
        assert len(rows) >= 7
        v, lo, hi, drivers = rows[0]
        assert lo <= v <= hi
        assert isinstance(drivers, (list, dict))

    # Backtest and check scores API
    s = (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%dT00:00:00+00:00")
    e = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")
    out_bt = run_backtests(target="heat", start=s, end=e, step_days=7)
    assert "metrics" in out_bt

    async with AsyncClient(app=app, base_url="http://test") as client:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "Viewer123!"},
        )
        cookies = r.cookies
        rid = 1
        scores = await client.get(f"/api/v1/models/scores?target=heat&regionId={rid}", cookies=cookies)
        assert scores.status_code == 200
        sc = scores.json()
        for k in ("rmse", "mae", "mean_pinball_loss"):
            assert k in sc

