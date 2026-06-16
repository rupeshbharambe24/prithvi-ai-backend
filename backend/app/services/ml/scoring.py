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
        # Normalize ts to tz-aware UTC before indexing/sorting (SQLite may
        # yield a mix of tz-naive and tz-aware timestamps).
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="mixed")
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
        fdf["target_date"] = pd.to_datetime(fdf["target_date"], utc=True, format="mixed").dt.normalize()
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
