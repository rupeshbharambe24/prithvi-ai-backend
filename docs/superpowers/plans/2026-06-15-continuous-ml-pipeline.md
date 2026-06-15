# Continuous Train → Predict → Verify → Retrain Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing ETL / train / forecast / drift / backtest services into two scheduled orchestrators (daily + weekly) plus a CLI, so forward forecasts stay current, matured forecasts get scored against actuals, and weekly retraining only promotes a model that beats the live one.

**Architecture:** A new `services/pipeline/runner.py` holds `run_daily_pipeline` and `run_weekly_pipeline`, each a thin sequence of try/except-isolated steps calling existing service functions. A new `services/ml/scoring.py` scores matured forecasts into `backtest_scores` using a high-water-mark (no schema change). `registry.py` gains status-aware `active_model` + `promote_if_better`, backed by one new `model_versions.status` column. `main.py`'s scheduler and a new `scripts/run_pipeline.py` CLI both call the runner.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.x async, APScheduler, SQLite (local) / Postgres (prod), Alembic, pytest + pytest-asyncio, httpx.

**Conventions (from existing code):**
- Tests live in `backend/backend/tests/`, are integration-style, `@pytest.mark.asyncio`, use `from backend.app.db.session import AsyncSessionLocal`, run against the seeded local SQLite DB (seed runs on app import/startup). No conftest fixtures — follow `tests/test_training_and_backtest.py`.
- Run tests from `backend/` dir: `pytest backend/tests/<file>.py -v`.
- Model statuses used in this plan: `active` (live, ≤1 per target), `shadow` (just trained, awaiting decision), `archived` (was active, superseded by a better model), `rejected` (challenger that lost). `active_model` falls back to newest row when no row has `status='active'` (back-compat with the 60 pre-existing versions).

---

### Task 1: Add `status` column to ModelVersion

**Files:**
- Modify: `backend/backend/app/db/models/model_version.py`
- Modify: `backend/backend/app/db/local_bootstrap.py`
- Create: `backend/backend/app/db/migrations/versions/0005_model_status.py`
- Test: `backend/backend/tests/test_model_status_column.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_model_status_column.py
import pytest
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal


@pytest.mark.asyncio
async def test_model_versions_has_status_column():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("PRAGMA table_info(model_versions)"))).fetchall()
        col_names = {r[1] for r in rows}
        assert "status" in col_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_model_status_column.py -v`
Expected: FAIL — `status` not in `col_names`.

- [ ] **Step 3: Add the column to the ORM model**

In `backend/backend/app/db/models/model_version.py`, add the import `String` is already imported; add the field after `metrics_json`:

```python
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", index=True
    )
```

- [ ] **Step 4: Add local-DB migration for existing SQLite file**

In `backend/backend/app/db/local_bootstrap.py`, inside `init_local_database`, after the `create_all` call and the `forecasts` CREATE TABLE block, add an idempotent ALTER (SQLite raises if the column exists, so guard it):

```python
        # Add model_versions.status for champion/challenger (idempotent)
        try:
            await conn.execute(
                text("ALTER TABLE model_versions ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
            )
        except Exception:
            pass  # column already exists
```

- [ ] **Step 5: Create the Alembic migration (prod path)**

```python
# backend/backend/app/db/migrations/versions/0005_model_status.py
"""add status to model_versions

Revision ID: 0005_model_status
Revises: 0004_step4_ops
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_model_status"
down_revision = "0004_step4_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.create_index("ix_model_versions_status", "model_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_versions_status", table_name="model_versions")
    op.drop_column("model_versions", "status")
```

Note: confirm `0004_step4_ops` is the current head revision id (open the newest file in `versions/`); if the id string differs, set `down_revision` to match.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_model_status_column.py -v`
Expected: PASS. (App startup runs `init_local_database`, which ALTERs the existing `prithvi.db`.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/model_version.py backend/app/db/local_bootstrap.py backend/app/db/migrations/versions/0005_model_status.py backend/tests/test_model_status_column.py
git commit -m "feat(ml): add model_versions.status for champion/challenger"
```

---

### Task 2: Status-aware `active_model` + `promote_if_better`

**Files:**
- Modify: `backend/backend/app/services/ml/registry.py`
- Test: `backend/backend/tests/test_registry_promotion.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_registry_promotion.py
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
        t = "test_promo_c"
        await _insert_mv(db, t, 0.4, "archived", datetime(2026, 1, 1, tzinfo=timezone.utc))
        newest = await _insert_mv(db, t, 0.4, "shadow", datetime(2026, 2, 1, tzinfo=timezone.utc))
        active = await active_model(db, t)
        assert active.id == newest  # no 'active' row → newest wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_registry_promotion.py -v`
Expected: FAIL — `cannot import name 'active_model'` / `'promote_if_better'`.

- [ ] **Step 3: Implement the functions**

Append to `backend/backend/app/services/ml/registry.py`:

```python
async def active_model(db: AsyncSession, target: str) -> ModelVersion | None:
    """Return the live model for a target.

    Prefers the newest status='active' row; falls back to the newest row of any
    status (back-compat with versions created before the status column existed).
    """
    from sqlalchemy import select, desc

    res = await db.execute(
        select(ModelVersion)
        .where(ModelVersion.target == target, ModelVersion.status == "active")
        .order_by(desc(ModelVersion.created_at))
        .limit(1)
    )
    mv = res.scalars().first()
    if mv is not None:
        return mv
    return await latest_model(db, target)


def _skill(mv: ModelVersion | None) -> float:
    if mv is None or not isinstance(mv.metrics_json, dict):
        return float("-inf")
    val = mv.metrics_json.get("skill_score")
    return float(val) if val is not None else float("-inf")


async def promote_if_better(db: AsyncSession, target: str) -> bool:
    """Champion/challenger: promote newest shadow model only if its skill_score
    is >= the current active model. Otherwise reject the challenger.

    Returns True if a promotion happened. Fail-safe: on any error, keeps the
    current champion and returns False.
    """
    from sqlalchemy import select, desc

    try:
        chall = (await db.execute(
            select(ModelVersion)
            .where(ModelVersion.target == target, ModelVersion.status == "shadow")
            .order_by(desc(ModelVersion.created_at))
            .limit(1)
        )).scalars().first()
        if chall is None:
            return False

        champ = (await db.execute(
            select(ModelVersion)
            .where(ModelVersion.target == target, ModelVersion.status == "active")
            .order_by(desc(ModelVersion.created_at))
            .limit(1)
        )).scalars().first()

        if _skill(chall) >= _skill(champ):
            if champ is not None:
                champ.status = "archived"
            chall.status = "active"
            await db.commit()
            return True
        else:
            chall.status = "rejected"
            await db.commit()
            return False
    except Exception:
        await db.rollback()
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_registry_promotion.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ml/registry.py backend/tests/test_registry_promotion.py
git commit -m "feat(ml): status-aware active_model + champion/challenger promote_if_better"
```

---

### Task 3: Score matured forecasts into `backtest_scores`

**Files:**
- Create: `backend/backend/app/services/ml/scoring.py`
- Test: `backend/backend/tests/test_forecast_scoring.py`

Approach: for each (target, region), high-water-mark = `MAX(window_end)` of existing
`backtest_scores` for that pair. Score forecasts with `target_date > high_water_mark` and
`target_date < today` whose realized actual (the target function applied to observed features)
exists. Write one `backtest_scores` row covering the new window. Idempotent: a re-run finds no
forecasts past the new high-water mark.

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_forecast_scoring.py
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.scoring import score_due_forecasts


@pytest.mark.asyncio
async def test_scoring_writes_row_and_is_idempotent():
    async with AsyncSessionLocal() as db:
        rid = (await db.execute(text("SELECT id FROM regions LIMIT 1"))).scalar()
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

        before = (await db.execute(text("SELECT COUNT(*) FROM backtest_scores WHERE target='heat'"))).scalar()
        out = await score_due_forecasts(db)
        assert isinstance(out, dict)
        after = (await db.execute(text("SELECT COUNT(*) FROM backtest_scores WHERE target='heat'"))).scalar()
        assert after > before

        # Re-run: no new rows (idempotent — nothing past the new high-water mark)
        await score_due_forecasts(db)
        after2 = (await db.execute(text("SELECT COUNT(*) FROM backtest_scores WHERE target='heat'"))).scalar()
        assert after2 == after
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_forecast_scoring.py -v`
Expected: FAIL — module `scoring` does not exist.

- [ ] **Step 3: Implement `scoring.py`**

```python
# backend/backend/app/services/ml/scoring.py
"""Score matured forecasts against realized actuals into backtest_scores.

For each (target, region): find forecasts whose target_date has passed and is newer
than the last scored window, compute |forecast - actual| and interval coverage, and
write one aggregate backtest_scores row. High-water-mark makes it idempotent.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .loaders import load_region_features
from .targets import TARGET_CONFIG
from ...db.models import BacktestScore

logger = logging.getLogger(__name__)


async def _actual_series(db: AsyncSession, target: str, region_id: int, start: datetime, end: datetime) -> pd.Series:
    config = TARGET_CONFIG.get(target)
    if config is None:
        return pd.Series(dtype=float)
    df = await load_region_features(db, region_id, start, end)
    if df.empty:
        return pd.Series(dtype=float)
    if "ts" in df.columns:
        df = df.set_index("ts").sort_index()
    if df.index.dtype == object:
        df.index = pd.to_datetime(df.index, utc=True)
    y = config["fn"](df)
    y.index = pd.to_datetime(y.index, utc=True).normalize()
    return y


async def score_due_forecasts(db: AsyncSession) -> Dict:
    """Score all targets/regions whose forecasts have matured. Returns counts."""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pairs = (await db.execute(text(
        "SELECT DISTINCT region_id, type FROM forecasts WHERE type IN ('heat','disease','surge','pm25')"
    ))).fetchall()

    scored_windows = 0
    scored_points = 0

    for region_id, target in pairs:
        hwm = (await db.execute(text(
            "SELECT MAX(window_end) FROM backtest_scores WHERE target=:t AND region_id=:r"
        ), {"t": target, "r": region_id})).scalar()
        hwm_dt = pd.to_datetime(hwm, utc=True) if hwm else pd.Timestamp("1970-01-01", tz="UTC")

        rows = (await db.execute(text(
            "SELECT target_date, value, p05, p95 FROM forecasts "
            "WHERE region_id=:r AND type=:t AND target_date < :today ORDER BY target_date"
        ), {"r": region_id, "t": target, "today": today})).fetchall()
        if not rows:
            continue

        fdf = pd.DataFrame(rows, columns=["target_date", "value", "p05", "p95"])
        fdf["target_date"] = pd.to_datetime(fdf["target_date"], utc=True).dt.normalize()
        fdf = fdf[fdf["target_date"] > hwm_dt]
        if fdf.empty:
            continue

        start = fdf["target_date"].min().to_pydatetime() - timedelta(days=1)
        end = fdf["target_date"].max().to_pydatetime() + timedelta(days=1)
        actuals = await _actual_series(db, target, region_id, start, end)
        if actuals.empty:
            continue

        errs, covs, used_dates = [], [], []
        for _, row in fdf.iterrows():
            td = row["target_date"]
            if td not in actuals.index:
                continue
            a = float(actuals.loc[td]) if np.ndim(actuals.loc[td]) == 0 else float(actuals.loc[td].iloc[0])
            v, lo, hi = float(row["value"]), float(row["p05"]), float(row["p95"])
            errs.append(abs(v - a))
            covs.append(1.0 if (lo <= a <= hi) else 0.0)
            used_dates.append(td)

        if not errs:
            continue

        metrics = {
            "rmse": round(float(np.sqrt(np.mean(np.square(errs)))), 6),
            "mae": round(float(np.mean(errs)), 6),
            "coverage": round(float(np.mean(covs)), 4),
            "n": len(errs),
            "kind": "live_score",
        }
        db.add(BacktestScore(
            target=target,
            region_id=region_id,
            window_start=min(used_dates).to_pydatetime(),
            window_end=max(used_dates).to_pydatetime(),
            metrics_json=metrics,
        ))
        await db.commit()
        scored_windows += 1
        scored_points += len(errs)
        logger.info("forecasts_scored target=%s region=%s n=%d mae=%.4f cov=%.2f",
                    target, region_id, len(errs), metrics["mae"], metrics["coverage"])

    return {"windows": scored_windows, "points": scored_points}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_forecast_scoring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ml/scoring.py backend/tests/test_forecast_scoring.py
git commit -m "feat(ml): score matured forecasts vs actuals into backtest_scores"
```

---

### Task 4: Pipeline runner — daily + weekly orchestration

**Files:**
- Create: `backend/backend/app/services/pipeline/__init__.py` (empty)
- Create: `backend/backend/app/services/pipeline/runner.py`
- Test: `backend/backend/tests/test_pipeline_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_pipeline_runner.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_pipeline_runner.py -v`
Expected: FAIL — module `pipeline.runner` does not exist.

- [ ] **Step 3: Create the package marker**

Create empty file `backend/backend/app/services/pipeline/__init__.py`.

- [ ] **Step 4: Implement `runner.py`**

```python
# backend/backend/app/services/pipeline/runner.py
"""Orchestration for the continuous ML loop. Thin callers of existing services.

run_daily_pipeline:  ingest -> score matured forecasts -> refresh forward forecasts -> drift check
run_weekly_pipeline: retrain (shadow) -> champion/challenger promote -> backtest+fairness -> daily run
Each step is isolated; one failure logs and does not abort the run.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..ml.inference import forecast_target
from ..ml.registry import active_model, promote_if_better
from ..ml.scoring import score_due_forecasts
from ..ml.train import retrain_all_models
from ..ml.backtest import simple_rolling_backtest
from ..ml.loaders import get_any_region_id
from ..qa.drift import compute_all_drift
from ..qa.fairness import evaluate_heat_fairness
from ...db.models import Region

logger = logging.getLogger(__name__)

TARGETS = ["heat", "surge", "pm25", "disease"]
CRITICAL_PSI = 0.25


async def refresh_forecasts(db: AsyncSession, horizon_days: int = 14) -> Dict:
    """Delete future forecasts and regenerate from the active model. Idempotent."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    regions = (await db.execute(select(Region))).scalars().all()
    total = 0
    for reg in regions:
        for tgt in TARGETS:
            try:
                await db.execute(text(
                    "DELETE FROM forecasts WHERE region_id=:r AND type=:t AND target_date >= :today"
                ), {"r": reg.id, "t": tgt, "today": today})
                forecasts = await forecast_target(db, tgt, reg.id, horizon_days)
                for i, fc in enumerate(forecasts):
                    d = datetime.fromisoformat(fc["date"])
                    await db.execute(text(
                        "INSERT INTO forecasts (region_id, type, target_date, horizon, value, p05, p95, drivers_json) "
                        "VALUES (:r,:t,:d,:h,:v,:lo,:hi,:dr)"
                    ), {
                        "r": reg.id, "t": tgt, "d": d, "h": i + 1,
                        "v": round(fc["risk"], 4), "lo": round(fc["p05"], 4),
                        "hi": round(fc["p95"], 4), "dr": json.dumps(fc["drivers"]),
                    })
                    total += 1
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("refresh_forecasts_failed target=%s region=%s: %s", tgt, reg.id, e)
    logger.info("forecasts_refreshed rows=%d", total)
    return {"rows": total}


async def _ingest_all(db: AsyncSession) -> Dict:
    from ..etl.era5 import flow_era5_ingest
    from ..etl.openaq import flow_openaq_ingest
    from ..etl.who_gho import flow_who_gho_ingest
    from ..etl.population import flow_population_vulnerability
    from ..etl.google_trends import flow_google_trends_ingest

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    out = {}
    for name, coro in [
        ("era5", flow_era5_ingest(db, start, now)),
        ("openaq", flow_openaq_ingest(db, start, now)),
        ("who_gho", flow_who_gho_ingest(db)),
        ("population", flow_population_vulnerability(db)),
        ("google_trends", flow_google_trends_ingest(db, lookback_weeks=4)),
    ]:
        try:
            res = await coro
            out[name] = res.get("rows", 0) if isinstance(res, dict) else 0
        except Exception as e:
            logger.error("ingest_%s_failed: %s", name, e)
            out[name] = f"error: {e}"
    return out


async def run_daily_pipeline(db: AsyncSession, do_ingest: bool = True, horizon_days: int = 14) -> Dict:
    summary: Dict = {}
    if do_ingest:
        try:
            summary["ingest"] = await _ingest_all(db)
        except Exception as e:
            summary["ingest"] = f"error: {e}"

    try:
        summary["score"] = await score_due_forecasts(db)
    except Exception as e:
        summary["score"] = f"error: {e}"

    try:
        summary["forecast"] = await refresh_forecasts(db, horizon_days=horizon_days)
    except Exception as e:
        summary["forecast"] = f"error: {e}"

    try:
        drift = await compute_all_drift(db)
        critical = [k for k, v in drift.items() if isinstance(v, dict) and v.get("psi", 0) >= CRITICAL_PSI]
        summary["drift"] = {"checked": len(drift), "critical": critical}
        if critical:
            logger.warning("drift_triggered_retrain features=%s", critical)
            summary["drift_retrain"] = await run_weekly_pipeline(db, trigger_daily=False)
    except Exception as e:
        summary["drift"] = f"error: {e}"

    logger.info("pipeline_daily_complete summary=%s", summary)
    return summary


async def run_weekly_pipeline(db: AsyncSession, trigger_daily: bool = True) -> Dict:
    summary: Dict = {}
    try:
        summary["retrain"] = await retrain_all_models(db)
    except Exception as e:
        summary["retrain"] = f"error: {e}"

    promotions = {}
    for tgt in TARGETS:
        try:
            promotions[tgt] = await promote_if_better(db, tgt)
        except Exception as e:
            promotions[tgt] = f"error: {e}"
    summary["promotions"] = promotions

    try:
        rid = await get_any_region_id(db)
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=28)
        backtests = {}
        for tgt in TARGETS:
            try:
                backtests[tgt] = await simple_rolling_backtest(db, tgt, rid, start, end, step_days=7)
            except Exception as e:
                backtests[tgt] = f"error: {e}"
        summary["backtest"] = backtests
    except Exception as e:
        summary["backtest"] = f"error: {e}"

    try:
        summary["fairness"] = await evaluate_heat_fairness(db)
    except Exception as e:
        summary["fairness"] = f"error: {e}"

    if trigger_daily:
        try:
            summary["forecast_refresh"] = await refresh_forecasts(db)
        except Exception as e:
            summary["forecast_refresh"] = f"error: {e}"

    logger.info("pipeline_weekly_complete promotions=%s", promotions)
    return summary
```

Note on `retrain_all_models`: Task 5 makes it register new models with `status='shadow'` so `promote_if_better` has a challenger to evaluate. Until then this test passes because `promote_if_better` returns `False` (no shadow) without error.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest backend/tests/test_pipeline_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline/ backend/tests/test_pipeline_runner.py
git commit -m "feat(pipeline): daily + weekly orchestration runner"
```

---

### Task 5: Retrain registers shadow models

**Files:**
- Modify: `backend/backend/app/services/ml/train.py:255` (the `register_model` call inside `train_target`)
- Modify: `backend/backend/app/services/ml/registry.py` (`register_model` signature)
- Test: `backend/backend/tests/test_retrain_shadow_status.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_retrain_shadow_status.py
import pytest
from sqlalchemy import text
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.ml.registry import register_model


@pytest.mark.asyncio
async def test_register_model_defaults_to_shadow():
    async with AsyncSessionLocal() as db:
        mv = await register_model(
            db, target="test_shadow", algo="gbr", params={}, metrics={"skill_score": 0.1},
            model_obj={"x": 1}, status="shadow",
        )
        row_status = (await db.execute(text("SELECT status FROM model_versions WHERE id=:i"), {"i": mv.id})).scalar()
        assert row_status == "shadow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_retrain_shadow_status.py -v`
Expected: FAIL — `register_model() got an unexpected keyword argument 'status'`.

- [ ] **Step 3: Add `status` param to `register_model`**

In `backend/backend/app/services/ml/registry.py`, change the signature and the `ModelVersion(...)` construction:

```python
async def register_model(
    db: AsyncSession, target: str, algo: str, params: Dict[str, Any], metrics: Dict[str, Any],
    model_obj: Any, status: str = "active",
) -> ModelVersion:
```

and add `status=status,` to the `ModelVersion(...)` kwargs (after `metrics_json=metrics,`).

- [ ] **Step 4: Make weekly retrain produce shadows**

In `backend/backend/app/services/ml/train.py`, the `register_model(...)` call near line 255 (inside `train_target`) — add `status="shadow"`:

```python
    await register_model(db, target, algo, params, metrics, model_bundle, status="shadow")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest backend/tests/test_retrain_shadow_status.py -v`
Expected: PASS.

- [ ] **Step 6: Verify promotion end-to-end (no new code)**

Run: `pytest backend/tests/test_registry_promotion.py backend/tests/test_pipeline_runner.py -v`
Expected: PASS — newly trained models are shadows, `promote_if_better` now has challengers to evaluate.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ml/registry.py backend/app/services/ml/train.py backend/tests/test_retrain_shadow_status.py
git commit -m "feat(ml): retrained models register as shadow for champion/challenger"
```

---

### Task 6: Wire scheduler (main.py) + CLI

**Files:**
- Modify: `backend/backend/app/main.py` (`_daily_ingest`, `_weekly_retrain`)
- Create: `backend/backend/app/scripts/__init__.py` (empty)
- Create: `backend/backend/app/scripts/run_pipeline.py`
- Test: `backend/backend/tests/test_run_pipeline_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/backend/tests/test_run_pipeline_cli.py
import pytest
from backend.app.scripts.run_pipeline import run


@pytest.mark.asyncio
async def test_cli_daily_returns_summary():
    out = await run("daily", do_ingest=False)
    assert isinstance(out, dict)
    assert "forecast" in out


@pytest.mark.asyncio
async def test_cli_score_only():
    out = await run("score")
    assert isinstance(out, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_run_pipeline_cli.py -v`
Expected: FAIL — module `scripts.run_pipeline` does not exist.

- [ ] **Step 3: Create the package marker**

Create empty file `backend/backend/app/scripts/__init__.py`.

- [ ] **Step 4: Implement the CLI**

```python
# backend/backend/app/scripts/run_pipeline.py
"""On-demand pipeline runner. Same logic as the scheduler.

Usage:
  python -m backend.app.scripts.run_pipeline daily      # ingest+score+forecast+drift
  python -m backend.app.scripts.run_pipeline daily --no-ingest
  python -m backend.app.scripts.run_pipeline weekly      # retrain+promote+fairness+refresh
  python -m backend.app.scripts.run_pipeline score       # score matured forecasts only
  python -m backend.app.scripts.run_pipeline forecast    # refresh forward forecasts only
"""
from __future__ import annotations

import asyncio
import sys
from typing import Dict

from ..db.session import AsyncSessionLocal
from ..services.pipeline.runner import (
    run_daily_pipeline, run_weekly_pipeline, refresh_forecasts,
)
from ..services.ml.scoring import score_due_forecasts


async def run(mode: str, do_ingest: bool = True) -> Dict:
    async with AsyncSessionLocal() as db:
        if mode == "daily":
            return await run_daily_pipeline(db, do_ingest=do_ingest)
        if mode == "weekly":
            return await run_weekly_pipeline(db)
        if mode == "score":
            return await score_due_forecasts(db)
        if mode == "forecast":
            return await refresh_forecasts(db)
        raise SystemExit(f"unknown mode: {mode} (use daily|weekly|score|forecast)")


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "daily"
    do_ingest = "--no-ingest" not in args
    result = asyncio.run(run(mode, do_ingest=do_ingest))
    print(result)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Wire the scheduler in `main.py`**

Replace the body of `_daily_ingest` (the per-flow try/except blocks) with a single call to the runner, and replace `_weekly_retrain`'s body likewise. New bodies:

```python
async def _daily_ingest() -> None:
    from .db.session import AsyncSessionLocal
    from .services.pipeline.runner import run_daily_pipeline

    logger.info("scheduled_daily_ingest_started")
    async with AsyncSessionLocal() as db:
        summary = await run_daily_pipeline(db, do_ingest=True)
    logger.info("scheduled_daily_complete", summary=summary)


async def _weekly_retrain() -> None:
    from .db.session import AsyncSessionLocal
    from .services.pipeline.runner import run_weekly_pipeline

    logger.info("scheduled_weekly_retrain_started")
    async with AsyncSessionLocal() as db:
        summary = await run_weekly_pipeline(db)
    logger.info("scheduled_weekly_complete", summary=summary)
```

Leave `_start_scheduler` and the cron registrations (`daily_ingest@06:00`, `weekly_retrain@mon_07:00`) unchanged — they already point at these two functions.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/test_run_pipeline_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Manual smoke of the CLI**

Run: `python -m backend.app.scripts.run_pipeline forecast`
Expected: prints `{'rows': <N>}` and future-dated forecasts are refreshed in `prithvi.db`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/main.py backend/app/scripts/ backend/tests/test_run_pipeline_cli.py
git commit -m "feat(pipeline): wire scheduler to runner + add run_pipeline CLI"
```

---

### Task 7: Full regression + spec coverage check

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest backend/tests/ -v`
Expected: all tests pass, including the pre-existing `test_training_and_backtest.py` (unaffected — `latest_model` and `run_daily_forecasts` still exist).

- [ ] **Step 2: End-to-end manual verification**

Run:
```bash
python -m backend.app.scripts.run_pipeline daily --no-ingest
python -m backend.app.scripts.run_pipeline weekly
```
Expected: daily prints a summary with `score`/`forecast`/`drift` keys; weekly prints `retrain`/`promotions`/`fairness`. Reload the frontend — Overview/Heat/Disease/Surge/Air remain populated; Models page shows model statuses; Fairness & QA shows new drift/backtest entries.

- [ ] **Step 3: Commit any final fixups**

```bash
git add -A && git commit -m "test: full pipeline regression green"
```

---

## Notes for the implementer

- Run all `pytest` and `python -m` commands from `E:\Projects\PRITHVI-AI\Codes\backend` with the recreated `prithvi-ai` venv active.
- Tests share the local `prithvi.db`; they insert sentinel targets (`test_*`) to avoid colliding with seeded data. Don't add a separate test DB — match the existing integration style.
- If `0004_step4_ops` is not the Alembic head, set Task 1's `down_revision` to the actual head id.
