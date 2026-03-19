"""Inference pipeline: load trained models and generate forecasts.

Uses the trained ensemble (XGBoost + optional StatsForecast) from registry.
Falls back to ad-hoc training if no registered model exists.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from .loaders import load_region_features
from .features import add_time_features, add_lags_rollings
from .targets import TARGET_CONFIG
from .explain import top_k_drivers
from .registry import latest_model, load_artifact
from ...db.models import Feature

logger = logging.getLogger(__name__)


async def forecast_target(
    db: AsyncSession,
    target: str,
    region_id: int,
    horizon_days: int = 7,
) -> List[Dict]:
    """Generate forecast for a target using the latest trained model.

    Returns list of dicts with date, risk/value, p05, p95, drivers.
    """
    config = TARGET_CONFIG.get(target)
    if config is None:
        logger.error("unknown_target: %s", target)
        return []

    # Try loading trained model from registry
    mv = await latest_model(db, target)
    bundle = None
    if mv and mv.path:
        try:
            bundle = load_artifact(mv.path)
        except Exception as e:
            logger.warning("load_model_failed for %s: %s", target, e)

    # Load recent features
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=120)
    df = await load_region_features(db, region_id, start, end)

    if "ts" in df.columns:
        df = df.set_index("ts").sort_index()
    if df.index.dtype == object:
        df.index = pd.to_datetime(df.index, utc=True)

    if bundle and isinstance(bundle, dict) and "xgb_model" in bundle:
        return _predict_from_bundle(df, bundle, config, horizon_days, mv)
    else:
        # Fallback: ad-hoc training
        return _predict_adhoc(df, config, horizon_days)


def _predict_from_bundle(
    df: pd.DataFrame,
    bundle: dict,
    config: dict,
    horizon_days: int,
    mv,
) -> List[Dict]:
    """Use trained model bundle for prediction."""
    xgb_model = bundle["xgb_model"]
    feature_names = bundle["feature_names"]
    normalize = bundle.get("normalize", True)

    # Build feature matrix
    exog_keys = config["exog_keys"]
    available = [k for k in exog_keys if k in df.columns]

    if not available:
        logger.warning("no_features_for_inference, using adhoc")
        return _predict_adhoc(df, config, horizon_days)

    X = df[available].copy()
    X = add_lags_rollings(X, available)
    X = add_time_features(X)
    X = X.dropna()

    if X.empty:
        return _predict_adhoc(df, config, horizon_days)

    # Ensure column alignment with training features
    for col in feature_names:
        if col not in X.columns:
            X[col] = 0.0
    X = X[feature_names]

    # Get SHAP drivers from recent data
    drivers = top_k_drivers(xgb_model, X.tail(min(50, len(X))), k=5)

    # Generate future predictions by extending last row
    last_row = X.tail(1)
    future_dates = pd.date_range(
        df.index[-1] + pd.Timedelta(days=1),
        periods=horizon_days,
        freq="D",
    )

    results = []
    model_rmse = 0.0
    if mv and mv.metrics_json:
        metrics = mv.metrics_json if isinstance(mv.metrics_json, dict) else {}
        model_rmse = metrics.get("rmse", 0.05)

    for i, dt in enumerate(future_dates):
        # Create feature row for this day
        X_fut = last_row.copy()
        # Update time features for the future date
        X_fut["doy"] = dt.dayofyear
        X_fut["dow"] = dt.dayofweek
        X_fut["sin_doy"] = np.sin(2 * np.pi * dt.dayofyear / 365.0)
        X_fut["cos_doy"] = np.cos(2 * np.pi * dt.dayofyear / 365.0)
        for d in range(7):
            if f"dow_{d}" in X_fut.columns:
                X_fut[f"dow_{d}"] = 1 if dt.dayofweek == d else 0

        # Ensure column order
        X_fut = X_fut[feature_names]

        yhat = float(xgb_model.predict(X_fut)[0])

        # Confidence interval from model RMSE
        uncertainty = model_rmse * 1.96 * (1 + 0.1 * i)  # widens with horizon
        p05 = yhat - uncertainty
        p95 = yhat + uncertainty

        if normalize:
            yhat = np.clip(yhat, 0.0, 1.0)
            p05 = np.clip(p05, 0.0, 1.0)
            p95 = np.clip(p95, 0.0, 1.0)

        p05 = min(p05, yhat)
        p95 = max(p95, yhat)

        results.append({
            "date": dt.date().isoformat(),
            "risk": round(float(yhat), 4),
            "p05": round(float(p05), 4),
            "p95": round(float(p95), 4),
            "drivers": drivers,
        })

    return results


def _predict_adhoc(df: pd.DataFrame, config: dict, horizon_days: int) -> List[Dict]:
    """Fallback: ad-hoc model training when no registered model exists."""
    from .models import fit_regression_with_quantiles, predict_with_uncertainty

    exog_keys = config["exog_keys"]
    base_cols = [c for c in exog_keys if c in df.columns]
    if not base_cols:
        base_cols = [c for c in ["heat_index", "t2m_max", "prcp_sum", "wet_bulb", "wbgt"] if c in df.columns]

    if not base_cols:
        # No data at all — return placeholder
        future_dates = pd.date_range(
            datetime.now(timezone.utc).date() + timedelta(days=1),
            periods=horizon_days, freq="D",
        )
        return [
            {"date": dt.date().isoformat(), "risk": 0.5, "p05": 0.3, "p95": 0.7, "drivers": []}
            for dt in future_dates
        ]

    X = add_time_features(add_lags_rollings(df[base_cols].copy(), base_cols))
    X = X.dropna().tail(90)
    if len(X) < 10:
        X = X.ffill().fillna(0.0)

    y = config["fn"](df).reindex(X.index)
    if y.isna().all():
        y = pd.Series(0.5, index=X.index)

    model = fit_regression_with_quantiles(X, y)
    future_dates = pd.date_range(df.index[-1] + pd.Timedelta(days=1), periods=horizon_days, freq="D")
    X_last = pd.concat([X.tail(1)] * horizon_days, ignore_index=True)
    X_last.index = range(len(X_last))
    yhat, p05, p95 = predict_with_uncertainty(model, X_last)
    drivers = top_k_drivers(model.model, X)

    out = []
    for i, dt in enumerate(future_dates):
        mu = float(np.clip(yhat[i], 0.0, 1.0)) if config["normalize"] else float(yhat[i])
        lo = float(np.clip(p05[i], 0.0, 1.0)) if config["normalize"] else float(p05[i])
        hi = float(np.clip(p95[i], 0.0, 1.0)) if config["normalize"] else float(p95[i])
        lo = min(lo, mu)
        hi = max(hi, mu)
        out.append({"date": dt.date().isoformat(), "risk": mu, "p05": lo, "p95": hi, "drivers": drivers})
    return out


# Backward compatibility alias
async def forecast_heat_risk(db: AsyncSession, region_id: int, horizon_days: int = 7) -> List[Dict]:
    return await forecast_target(db, "heat", region_id, horizon_days)
