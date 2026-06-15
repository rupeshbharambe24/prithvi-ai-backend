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
    region_ids = [r.id for r in regions]  # plain ints: safe to use after a rollback expires ORM state
    total = 0
    for rid in region_ids:
        for tgt in TARGETS:
            try:
                await db.execute(text(
                    "DELETE FROM forecasts WHERE region_id=:r AND type=:t AND target_date >= :today"
                ), {"r": rid, "t": tgt, "today": today})
                forecasts = await forecast_target(db, tgt, rid, horizon_days)
                for i, fc in enumerate(forecasts):
                    d = datetime.fromisoformat(fc["date"])
                    await db.execute(text(
                        "INSERT INTO forecasts (region_id, type, target_date, horizon, value, p05, p95, drivers_json) "
                        "VALUES (:r,:t,:d,:h,:v,:lo,:hi,:dr)"
                    ), {
                        "r": rid, "t": tgt, "d": d, "h": i + 1,
                        "v": round(fc["risk"], 4), "lo": round(fc["p05"], 4),
                        "hi": round(fc["p95"], 4), "dr": json.dumps(fc["drivers"]),
                    })
                    total += 1
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error("refresh_forecasts_failed target=%s region=%s: %s", tgt, rid, e)
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
