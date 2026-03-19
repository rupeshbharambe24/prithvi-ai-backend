"""Real rolling-window expanding backtest.

Train on [start..t], test on [t..t+step], advance by step_days.
Compares model against persistence baseline (yesterday = tomorrow).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from .metrics import rmse, mae, pinball_loss
from .loaders import load_region_features
from .features import add_time_features, add_lags_rollings
from .targets import TARGET_CONFIG
from ...db.models import BacktestScore, Region

logger = logging.getLogger(__name__)

MIN_TRAIN_SIZE = 30


async def write_backtest_score(
    db: AsyncSession,
    target: str,
    region_id: int,
    window_start: datetime,
    window_end: datetime,
    metrics: Dict[str, float],
) -> None:
    row = BacktestScore(
        target=target,
        region_id=region_id,
        window_start=window_start,
        window_end=window_end,
        metrics_json=metrics,
    )
    db.add(row)
    await db.commit()


async def simple_rolling_backtest(
    db: AsyncSession,
    target: str,
    region_id: int,
    start: datetime,
    end: datetime,
    step_days: int = 7,
) -> Dict[str, float]:
    """Real rolling-window expanding backtest.

    For each window:
    1. Train on [start..t] using XGBoost (or GBR)
    2. Predict on [t..t+step]
    3. Compare against actual values and persistence baseline
    """
    config = TARGET_CONFIG.get(target)
    if config is None:
        return {"rmse": 0.0, "mae": 0.0, "error": "unknown_target"}

    # Load all features for the period
    df = await load_region_features(db, region_id, start, end)

    if df.empty or len(df) < MIN_TRAIN_SIZE + step_days:
        logger.warning("insufficient_data_for_backtest %s region=%d", target, region_id)
        # Fall back to minimal metrics
        return await _fallback_backtest(db, target, region_id, start, end)

    if "ts" in df.columns:
        df = df.set_index("ts").sort_index()
    if df.index.dtype == object:
        df.index = pd.to_datetime(df.index, utc=True)

    # Compute target
    y_full = config["fn"](df)

    # Build feature matrix
    exog_keys = config["exog_keys"]
    available = [k for k in exog_keys if k in df.columns]
    if not available:
        return await _fallback_backtest(db, target, region_id, start, end)

    X_full = df[available].copy()
    X_full = add_lags_rollings(X_full, available)
    X_full = add_time_features(X_full)

    # Align and drop NaN
    common = X_full.index.intersection(y_full.index)
    X_full = X_full.loc[common]
    y_full = y_full.loc[common]
    mask = X_full.notna().all(axis=1) & y_full.notna()
    X_full = X_full[mask]
    y_full = y_full[mask]

    if len(X_full) < MIN_TRAIN_SIZE + step_days:
        return await _fallback_backtest(db, target, region_id, start, end)

    # Rolling window backtest
    all_y_true: List[float] = []
    all_y_pred: List[float] = []
    all_y_persist: List[float] = []
    n_windows = 0

    for t in range(MIN_TRAIN_SIZE, len(X_full) - step_days, step_days):
        X_train = X_full.iloc[:t]
        y_train = y_full.iloc[:t]
        X_test = X_full.iloc[t:t + step_days]
        y_test = y_full.iloc[t:t + step_days]

        if len(X_test) == 0:
            continue

        try:
            # Try XGBoost first
            try:
                import xgboost as xgb
                model = xgb.XGBRegressor(
                    n_estimators=100,
                    max_depth=3,
                    learning_rate=0.1,
                    verbosity=0,
                    random_state=42,
                )
                model.fit(X_train, y_train, verbose=False)
            except ImportError:
                from sklearn.ensemble import GradientBoostingRegressor
                model = GradientBoostingRegressor(
                    n_estimators=100, max_depth=3, learning_rate=0.1, random_state=42,
                )
                model.fit(X_train, y_train)

            y_pred = model.predict(X_test)
            if config["normalize"]:
                y_pred = np.clip(y_pred, 0.0, 1.0)

            # Persistence baseline
            y_persist = y_full.iloc[t - 1:t + step_days - 1].values

            all_y_true.extend(y_test.values.tolist())
            all_y_pred.extend(y_pred.tolist())
            all_y_persist.extend(y_persist[:len(y_test)].tolist())
            n_windows += 1

        except Exception as e:
            logger.warning("backtest_window_%d_failed: %s", t, e)
            continue

    if not all_y_true:
        return await _fallback_backtest(db, target, region_id, start, end)

    y_true_arr = np.array(all_y_true)
    y_pred_arr = np.array(all_y_pred)
    y_persist_arr = np.array(all_y_persist)

    model_rmse = rmse(y_true_arr, y_pred_arr)
    model_mae = mae(y_true_arr, y_pred_arr)
    persist_rmse = rmse(y_true_arr, y_persist_arr)

    skill = 1.0 - (model_rmse / persist_rmse) if persist_rmse > 0 else 0.0

    metrics = {
        "rmse": round(float(model_rmse), 6),
        "mae": round(float(model_mae), 6),
        "persistence_rmse": round(float(persist_rmse), 6),
        "skill_score": round(float(skill), 4),
        "n_windows": n_windows,
        "total_test_points": len(all_y_true),
    }

    await write_backtest_score(db, target, region_id, start, end, metrics)
    logger.info("backtest %s region=%d: RMSE=%.4f skill=%.2f (%d windows)",
                target, region_id, model_rmse, skill, n_windows)

    return metrics


async def _fallback_backtest(
    db: AsyncSession,
    target: str,
    region_id: int,
    start: datetime,
    end: datetime,
) -> Dict[str, float]:
    """Minimal backtest when insufficient data exists."""
    metrics = {
        "rmse": 0.0,
        "mae": 0.0,
        "persistence_rmse": 0.0,
        "skill_score": 0.0,
        "n_windows": 0,
        "total_test_points": 0,
        "note": "insufficient_data",
    }
    await write_backtest_score(db, target, region_id, start, end, metrics)
    return metrics
