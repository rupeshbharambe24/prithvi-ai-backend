"""Core ML training pipeline: XGBoost with optional StatsForecast ensemble.

Per-region, per-target training:
1. Load features from DB (lookback period)
2. Compute target variable
3. Train/test split (last 30 days = test)
4. XGBoost: Gradient boosted trees with exogenous features + time + lags
5. Optional: StatsForecast AutoETS for trend/seasonality baseline
6. Compute RMSE/MAE on test set
7. Extract SHAP top-5 drivers
8. Register model artifact
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .features import add_time_features, add_lags_rollings
from .targets import TARGET_CONFIG
from .loaders import load_region_features
from .explain import top_k_drivers
from .metrics import rmse, mae
from .registry import register_model
from ...db.models import Region

logger = logging.getLogger(__name__)

# Minimum rows needed for meaningful training
MIN_TRAIN_ROWS = 30
TEST_DAYS = 30
LOOKBACK_DAYS = 365


@dataclass
class TrainedEnsemble:
    """Container for a trained ensemble model."""
    xgb_model: Any
    feature_names: List[str]
    target: str
    region_id: int
    metrics: Dict[str, float] = field(default_factory=dict)
    drivers: List[Dict] = field(default_factory=list)
    sf_model: Any = None  # Optional StatsForecast model


def _prepare_features(df: pd.DataFrame, target_config: dict) -> pd.DataFrame:
    """Build feature matrix from raw features DataFrame."""
    exog_keys = target_config["exog_keys"]
    available = [k for k in exog_keys if k in df.columns]
    if not available:
        return pd.DataFrame()

    X = df[available].copy()
    X = add_lags_rollings(X, available)
    X = add_time_features(X)

    # Autoregressive target: keep only LAGGED values of the target's own
    # observation. Drop the contemporaneous column and any current-including
    # rolling mean, which would leak the target into the features.
    ar_key = target_config.get("ar_key")
    if ar_key:
        leak_cols = [c for c in X.columns if c == ar_key or c.startswith(f"{ar_key}_roll")]
        X = X.drop(columns=leak_cols, errors="ignore")
    return X


def _try_xgboost(X_train, y_train, X_test, y_test):
    """Try training with XGBoost. Falls back to sklearn GBR if unavailable."""
    try:
        import xgboost as xgb
        model = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=0.1,
            reg_lambda=1.0,
            random_state=42,
            verbosity=0,
        )
        model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )
        return model, "xgboost"
    except ImportError:
        logger.info("xgboost not available, using sklearn GBR")
        from sklearn.ensemble import GradientBoostingRegressor
        model = GradientBoostingRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )
        model.fit(X_train, y_train)
        return model, "gbr"


def _try_statsforecast(y_series: pd.Series):
    """Try fitting StatsForecast AutoETS for trend/seasonality baseline."""
    try:
        from statsforecast import StatsForecast
        from statsforecast.models import AutoETS, AutoARIMA

        # StatsForecast needs specific format
        sf_df = pd.DataFrame({
            "unique_id": "target",
            "ds": y_series.index,
            "y": y_series.values,
        })
        sf = StatsForecast(
            models=[AutoETS(season_length=7)],
            freq="D",
        )
        sf.fit(sf_df)
        return sf
    except ImportError:
        logger.info("statsforecast not available, skipping trend model")
        return None
    except Exception as e:
        logger.warning("statsforecast_fit_failed: %s", e)
        return None


async def train_target(
    db: AsyncSession,
    target: str,
    region_id: int,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[TrainedEnsemble]:
    """Train a model for a specific target and region.

    Returns TrainedEnsemble or None if insufficient data.
    """
    config = TARGET_CONFIG.get(target)
    if config is None:
        logger.error("unknown_target: %s", target)
        return None

    # Load features
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    df = await load_region_features(db, region_id, start, end)

    if df.empty or len(df) < MIN_TRAIN_ROWS:
        logger.warning("insufficient_data for %s region=%d: %d rows", target, region_id, len(df))
        return None

    # Set index
    if "ts" in df.columns:
        df = df.set_index("ts").sort_index()

    # Parse dates if stored as strings (SQLite)
    if df.index.dtype == object:
        df.index = pd.to_datetime(df.index, utc=True)

    # Compute target
    y = config["fn"](df)

    # Build feature matrix
    X = _prepare_features(df, config)
    if X.empty:
        logger.warning("no_features_available for %s region=%d", target, region_id)
        return None

    # Align X and y, drop NaN rows
    common_idx = X.index.intersection(y.index)
    X = X.loc[common_idx]
    y = y.loc[common_idx]

    # Drop rows with NaN
    mask = X.notna().all(axis=1) & y.notna()
    X = X[mask]
    y = y[mask]

    if len(X) < MIN_TRAIN_ROWS:
        logger.warning("too_few_valid_rows for %s region=%d: %d", target, region_id, len(X))
        return None

    # Train/test split (last TEST_DAYS = test)
    split_idx = max(len(X) - TEST_DAYS, int(len(X) * 0.7))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    if len(X_train) < 10 or len(X_test) < 3:
        logger.warning("split_too_small for %s region=%d", target, region_id)
        return None

    # Train XGBoost (or GBR fallback)
    xgb_model, algo = _try_xgboost(X_train, y_train, X_test, y_test)

    # Predictions
    y_pred = xgb_model.predict(X_test)
    if config["normalize"]:
        y_pred = np.clip(y_pred, 0.0, 1.0)

    # Metrics
    test_rmse = rmse(y_test.values, y_pred)
    test_mae = mae(y_test.values, y_pred)

    # Persistence baseline (yesterday = tomorrow)
    y_persist = y_test.shift(1).bfill()
    persist_rmse = rmse(y_test.values, y_persist.values)

    # Skill score: 1 - (model_rmse / baseline_rmse)
    skill = 1.0 - (test_rmse / persist_rmse) if persist_rmse > 0 else 0.0

    metrics = {
        "rmse": round(float(test_rmse), 6),
        "mae": round(float(test_mae), 6),
        "persistence_rmse": round(float(persist_rmse), 6),
        "skill_score": round(float(skill), 4),
        "train_rows": len(X_train),
        "test_rows": len(X_test),
    }

    # SHAP drivers
    drivers = top_k_drivers(xgb_model, X_test, k=5)

    # Optional: StatsForecast trend model
    sf_model = _try_statsforecast(y_train)

    logger.info(
        "trained %s region=%d: RMSE=%.4f MAE=%.4f skill=%.2f (%s)",
        target, region_id, test_rmse, test_mae, skill, algo,
    )

    ensemble = TrainedEnsemble(
        xgb_model=xgb_model,
        feature_names=list(X.columns),
        target=target,
        region_id=region_id,
        metrics=metrics,
        drivers=drivers,
        sf_model=sf_model,
    )

    # Register model artifact
    model_bundle = {
        "xgb_model": xgb_model,
        "feature_names": list(X.columns),
        "sf_model": sf_model,
        "target": target,
        "region_id": region_id,
        "normalize": config["normalize"],
    }
    params = {
        "algo": algo,
        "n_estimators": 200,
        "max_depth": 4,
        "learning_rate": 0.05,
    }
    await register_model(db, target, algo, params, metrics, model_bundle, status="shadow")

    return ensemble


async def retrain_all_models(db: AsyncSession) -> Dict[str, Any]:
    """Retrain models for all targets and all regions."""
    regions = (await db.execute(select(Region))).scalars().all()
    results = {}

    for reg in regions:
        for target in TARGET_CONFIG:
            key = f"{target}_{reg.name}"
            try:
                ensemble = await train_target(db, target, reg.id)
                if ensemble:
                    results[key] = {
                        "status": "success",
                        "metrics": ensemble.metrics,
                    }
                else:
                    results[key] = {"status": "skipped", "reason": "insufficient_data"}
            except Exception as e:
                logger.error("train_failed %s region=%s: %s", target, reg.name, e)
                results[key] = {"status": "error", "error": str(e)}

    logger.info("retrain_all_complete: %d models", len(results))
    return results
