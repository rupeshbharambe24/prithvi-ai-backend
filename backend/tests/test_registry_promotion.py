import pytest
from datetime import datetime, timezone
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.registry import active_model, promote_if_better


async def _insert_mv(db, target, skill, status, ts):
    cur = await db.execute(text(
        "INSERT INTO model_versions (target, algo, params_json, created_at, path, metrics_json, status) "
        "VALUES (:t,'gbr','{}',:c,'/tmp/none', :m, :s) RETURNING id"
    ), {"t": target, "c": ts, "m": f'{{"skill_score": {skill}}}', "s": status})
    mid = cur.scalar()
    await db.commit()
    return mid


@pytest.mark.asyncio
async def test_promote_better_challenger_wins():
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM model_versions WHERE target=:t"), {"t": "test_promo_a"})
        await db.commit()
        t = "test_promo_a"
        champ = await _insert_mv(db, t, 0.30, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
        chall = await _insert_mv(db, t, 0.50, "shadow", datetime(2026, 1, 8, tzinfo=timezone.utc))
        promoted = await promote_if_better(db, t)
        assert promoted is True
        active = await active_model(db, t)
        assert active.id == chall
        champ_status = (await db.execute(text("SELECT status FROM model_versions WHERE id=:i"), {"i": champ})).scalar()
        assert champ_status == "archived"


@pytest.mark.asyncio
async def test_reject_worse_challenger():
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM model_versions WHERE target=:t"), {"t": "test_promo_b"})
        await db.commit()
        t = "test_promo_b"
        champ = await _insert_mv(db, t, 0.60, "active", datetime(2026, 1, 1, tzinfo=timezone.utc))
        chall = await _insert_mv(db, t, 0.20, "shadow", datetime(2026, 1, 8, tzinfo=timezone.utc))
        promoted = await promote_if_better(db, t)
        assert promoted is False
        active = await active_model(db, t)
        assert active.id == champ
        chall_status = (await db.execute(text("SELECT status FROM model_versions WHERE id=:i"), {"i": chall})).scalar()
        assert chall_status == "rejected"


@pytest.mark.asyncio
async def test_active_model_fallback_to_latest_when_no_status():
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM model_versions WHERE target=:t"), {"t": "test_promo_c"})
        await db.commit()
        t = "test_promo_c"
        await _insert_mv(db, t, 0.4, "archived", datetime(2026, 1, 1, tzinfo=timezone.utc))
        newest = await _insert_mv(db, t, 0.4, "shadow", datetime(2026, 2, 1, tzinfo=timezone.utc))
        active = await active_model(db, t)
        assert active.id == newest  # no 'active' row → newest wins
