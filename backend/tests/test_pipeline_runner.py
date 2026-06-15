import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.pipeline.runner import refresh_forecasts, run_daily_pipeline


@pytest.mark.asyncio
async def test_refresh_forecasts_creates_future_and_no_duplicates():
    async with AsyncSessionLocal() as db:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        res1 = await refresh_forecasts(db, horizon_days=7)
        assert res1["rows"] > 0
        cnt1 = (await db.execute(text(
            "SELECT COUNT(*) FROM forecasts WHERE type='heat' AND target_date >= :t"
        ), {"t": today})).scalar()
        # Re-run must not accumulate duplicates (delete-then-insert)
        await refresh_forecasts(db, horizon_days=7)
        cnt2 = (await db.execute(text(
            "SELECT COUNT(*) FROM forecasts WHERE type='heat' AND target_date >= :t"
        ), {"t": today})).scalar()
        assert cnt2 == cnt1


@pytest.mark.asyncio
async def test_run_daily_pipeline_returns_summary():
    async with AsyncSessionLocal() as db:
        out = await run_daily_pipeline(db, do_ingest=False)  # skip live network in test
        assert set(["score", "forecast", "drift"]).issubset(out.keys())
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        future = (await db.execute(text(
            "SELECT COUNT(*) FROM forecasts WHERE target_date >= :t"
        ), {"t": today})).scalar()
        assert future > 0
