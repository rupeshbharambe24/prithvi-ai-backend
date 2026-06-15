import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.registry import promote_if_better, active_model


async def _mk(db, target, skill, status, ts):
    await db.execute(text(
        "INSERT INTO model_versions (target, algo, params_json, created_at, path, metrics_json, status) "
        "VALUES (:t,'gbr','{}',:c,'/tmp/none',:m,:s)"
    ), {"t": target, "c": ts, "m": f'{{"skill_score": {skill}}}', "s": status})
    await db.commit()


@pytest.mark.asyncio
async def test_at_most_one_active_and_no_pending_shadows_after_promote():
    t = "test_invariant_x"
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM model_versions WHERE target=:t"), {"t": t})
        await db.commit()
        # Simulate a polluted state: 3 active legacy rows + 2 shadow challengers
        await _mk(db, t, 0.10, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
        await _mk(db, t, 0.20, "active", datetime(2026, 1, 2, tzinfo=timezone.utc))
        await _mk(db, t, 0.30, "active", datetime(2026, 1, 3, tzinfo=timezone.utc))
        await _mk(db, t, 0.40, "shadow", datetime(2026, 2, 1, tzinfo=timezone.utc))
        await _mk(db, t, 0.55, "shadow", datetime(2026, 2, 8, tzinfo=timezone.utc))  # newest, best

        promoted = await promote_if_better(db, t)
        assert promoted is True

        n_active = (await db.execute(text("SELECT COUNT(*) FROM model_versions WHERE target=:t AND status='active'"), {"t": t})).scalar()
        n_shadow = (await db.execute(text("SELECT COUNT(*) FROM model_versions WHERE target=:t AND status='shadow'"), {"t": t})).scalar()
        assert n_active == 1, f"expected exactly 1 active, got {n_active}"
        assert n_shadow == 0, f"expected 0 pending shadows, got {n_shadow}"

        active = await active_model(db, t)
        assert abs(active.metrics_json["skill_score"] - 0.55) < 1e-9  # the best/newest shadow won

        # cleanup
        await db.execute(text("DELETE FROM model_versions WHERE target=:t"), {"t": t})
        await db.commit()
