import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.scoring import score_due_forecasts


@pytest.mark.asyncio
async def test_scoring_writes_row_and_is_idempotent():
    async with AsyncSessionLocal() as db:
        # Dedicated sentinel region so the test never collides with seeded data
        # and is fully re-runnable. Purge any prior sentinel region AND its
        # dependent rows first: SQLite recycles the max rowid, so a bare
        # DELETE on regions would leave orphaned forecasts/features/scores that
        # the recreated region (same id) inherits, defeating idempotency.
        old_ids = [r[0] for r in (await db.execute(text(
            "SELECT id FROM regions WHERE code='TEST_SCORE'"
        ))).fetchall()]
        for oid in old_ids:
            await db.execute(text("DELETE FROM backtest_scores WHERE region_id=:r"), {"r": oid})
            await db.execute(text("DELETE FROM forecasts WHERE region_id=:r"), {"r": oid})
            await db.execute(text("DELETE FROM features WHERE region_id=:r"), {"r": oid})
        await db.execute(text("DELETE FROM regions WHERE code='TEST_SCORE'"))
        await db.commit()
        rid = (await db.execute(text(
            "INSERT INTO regions (name, code) VALUES ('TestScoreRegion','TEST_SCORE') RETURNING id"
        ))).scalar()
        await db.commit()

        # A matured forecast 2 days ago + a matching heat_index feature actual
        d = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        await db.execute(text(
            "INSERT INTO forecasts (region_id, type, target_date, horizon, value, p05, p95, drivers_json) "
            "VALUES (:r,'heat',:d,2,0.6,0.4,0.8,'[]')"
        ), {"r": rid, "d": d})
        await db.execute(text(
            "INSERT INTO features (region_id, feature_key, ts, value, unit) VALUES (:r,'heat_index',:d,35.0,'C')"
        ), {"r": rid, "d": d})
        await db.commit()

        before = (await db.execute(text(
            "SELECT COUNT(*) FROM backtest_scores WHERE target='heat' AND region_id=:r"
        ), {"r": rid})).scalar()
        out = await score_due_forecasts(db)
        assert isinstance(out, dict)
        after = (await db.execute(text(
            "SELECT COUNT(*) FROM backtest_scores WHERE target='heat' AND region_id=:r"
        ), {"r": rid})).scalar()
        assert after > before

        # Re-run: no new rows for this region (idempotent — nothing past the new high-water mark)
        await score_due_forecasts(db)
        after2 = (await db.execute(text(
            "SELECT COUNT(*) FROM backtest_scores WHERE target='heat' AND region_id=:r"
        ), {"r": rid})).scalar()
        assert after2 == after
