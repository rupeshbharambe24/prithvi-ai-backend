"""Target variable extraction from features table.

Each target function takes a pivoted DataFrame (from load_region_features)
and returns a Series aligned to the DataFrame's index.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def heat_risk_target(df: pd.DataFrame) -> pd.Series:
    """Normalized heat risk (0-1) from heat_index and wbgt."""
    cols = [c for c in ["heat_index", "wbgt"] if c in df.columns]
    if not cols:
        return pd.Series(0.5, index=df.index)
    proxy = df[cols].mean(axis=1)
    x = proxy.ffill().bfill()
    if x.max() == x.min():
        return pd.Series(0.5, index=df.index)
    return ((x - x.min()) / (x.max() - x.min())).clip(0, 1)


def disease_risk_target(df: pd.DataFrame) -> pd.Series:
    """Disease risk proxy from heat_index + humidity (correlated with vector-borne disease).

    Without real case data, we use a climate-based proxy: high heat + high humidity
    → favorable conditions for dengue/malaria vectors.
    """
    hi = df.get("heat_index", pd.Series(30.0, index=df.index))
    rh = df.get("rh_mean", pd.Series(60.0, index=df.index))
    prcp = df.get("prcp_sum", pd.Series(0.0, index=df.index))

    # Normalized proxy: high temp + high humidity + rainfall → higher disease risk
    hi_norm = (hi.ffill().bfill() - 20) / 30  # normalize roughly 20-50°C → 0-1
    rh_norm = (rh.ffill().bfill() - 30) / 70  # normalize roughly 30-100% → 0-1
    prcp_norm = (prcp.ffill().bfill()).clip(0, 50) / 50  # normalize 0-50mm → 0-1

    risk = (0.4 * hi_norm + 0.3 * rh_norm + 0.3 * prcp_norm).clip(0, 1)
    return risk


def surge_target(df: pd.DataFrame) -> pd.Series:
    """Hospital surge proxy from heat stress indicators.

    ED visits correlate with extreme heat events. Without real ED data,
    we use heat_index exceedance above health thresholds.
    """
    hi = df.get("heat_index", pd.Series(30.0, index=df.index)).ffill().bfill()
    pm25 = df.get("pm25_obs", pd.Series(50.0, index=df.index)).ffill().bfill()

    # Heat-related ED visits surge when heat index > 40°C
    heat_surge = ((hi - 35) / 15).clip(0, 1)
    # PM2.5-related respiratory ED visits
    air_surge = ((pm25 - 50) / 150).clip(0, 1)

    # Combined surge index (0-1)
    surge = (0.6 * heat_surge + 0.4 * air_surge).clip(0, 1)
    return surge


def pm25_target(df: pd.DataFrame) -> pd.Series:
    """PM2.5 concentration from features table."""
    if "pm25_obs" in df.columns:
        return df["pm25_obs"].ffill().bfill().clip(0, 500)
    # Fallback: use any available air quality proxy
    return pd.Series(50.0, index=df.index)


# Map target names to (target_fn, exogenous_feature_keys, normalize_01)
TARGET_CONFIG = {
    "heat": {
        "fn": heat_risk_target,
        "exog_keys": ["t2m_max", "t2m_min", "rh_mean", "wind_max", "prcp_sum"],
        "normalize": True,
    },
    "disease": {
        "fn": disease_risk_target,
        "exog_keys": ["prcp_sum", "rh_mean", "t2m_max", "heat_index"],
        "normalize": True,
    },
    "surge": {
        "fn": surge_target,
        "exog_keys": ["heat_index", "pm25_obs", "t2m_max", "rh_mean"],
        "normalize": True,
    },
    "pm25": {
        "fn": pm25_target,
        "exog_keys": ["wind_max", "t2m_max", "rh_mean", "prcp_sum"],
        "normalize": False,
    },
}
