"""Target variable extraction from features table.

Each target function takes a pivoted DataFrame (from load_region_features)
and returns a Series aligned to the DataFrame's index.

Targets prefer real outcome data when available (WHO dengue counts,
Google Trends health searches) and fall back to climate proxies only
when real data is absent.
"""
from __future__ import annotations

import logging

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


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
    """Disease risk from real data sources when available.

    Priority order:
    1. Google Trends 'dengue_search' — real-time surveillance proxy
       (validated: Ginsberg et al. 2009, Yang et al. 2015)
    2. WHO GHO dengue case counts (annual, interpolated to daily)
    3. Climate-based proxy (fallback only)
    """
    # Priority 1: Google Trends dengue search volume (0-100 scale)
    if "dengue_search" in df.columns:
        trends = df["dengue_search"].ffill().bfill()
        non_null = trends.dropna()
        if len(non_null) > 5 and non_null.std() > 0:
            normalized = (trends - trends.min()) / (trends.max() - trends.min() + 1e-8)
            logger.debug("disease_risk using Google Trends dengue_search data")
            return normalized.clip(0, 1)

    # Priority 2: WHO dengue case counts from observations
    # (These are stored as annual national values in observations table,
    #  but if interpolated to features they appear here)
    if "dengue_cases" in df.columns:
        cases = df["dengue_cases"].ffill().bfill()
        non_null = cases.dropna()
        if len(non_null) > 3 and non_null.std() > 0:
            normalized = (cases - cases.min()) / (cases.max() - cases.min() + 1e-8)
            logger.debug("disease_risk using WHO dengue case counts")
            return normalized.clip(0, 1)

    # Priority 3: Google Trends respiratory/hospital searches
    for alt_key in ["respiratory_search", "hospital_search"]:
        if alt_key in df.columns:
            alt = df[alt_key].ffill().bfill()
            non_null = alt.dropna()
            if len(non_null) > 5 and non_null.std() > 0:
                normalized = (alt - alt.min()) / (alt.max() - alt.min() + 1e-8)
                logger.debug("disease_risk using %s as proxy", alt_key)
                return normalized.clip(0, 1)

    # Fallback: climate proxy (clearly labeled)
    logger.debug("disease_risk falling back to climate proxy (no real outcome data)")
    hi = df.get("heat_index", pd.Series(30.0, index=df.index))
    rh = df.get("rh_mean", pd.Series(60.0, index=df.index))
    prcp = df.get("prcp_sum", pd.Series(0.0, index=df.index))

    hi_norm = (hi.ffill().bfill() - 20) / 30
    rh_norm = (rh.ffill().bfill() - 30) / 70
    prcp_norm = (prcp.ffill().bfill()).clip(0, 50) / 50

    risk = (0.4 * hi_norm + 0.3 * rh_norm + 0.3 * prcp_norm).clip(0, 1)
    return risk


def surge_target(df: pd.DataFrame) -> pd.Series:
    """Hospital surge from real search data or climate proxy.

    Priority order:
    1. Google Trends 'heatstroke_search' + 'hospital_search' — direct ER proxy
    2. Climate-based proxy (fallback)
    """
    # Priority 1: Google Trends hospital/heatstroke search volume
    search_cols = [c for c in ["heatstroke_search", "hospital_search"] if c in df.columns]
    if search_cols:
        search_data = df[search_cols].ffill().bfill()
        non_null = search_data.dropna()
        if len(non_null) > 5:
            combined = search_data.mean(axis=1)
            if combined.std() > 0:
                normalized = (combined - combined.min()) / (combined.max() - combined.min() + 1e-8)
                logger.debug("surge_target using Google Trends search data")
                return normalized.clip(0, 1)

    # Fallback: climate-based proxy
    logger.debug("surge_target falling back to climate proxy")
    hi = df.get("heat_index", pd.Series(30.0, index=df.index)).ffill().bfill()
    pm25 = df.get("pm25_obs", pd.Series(50.0, index=df.index)).ffill().bfill()

    heat_surge = ((hi - 35) / 15).clip(0, 1)
    air_surge = ((pm25 - 50) / 150).clip(0, 1)

    surge = (0.6 * heat_surge + 0.4 * air_surge).clip(0, 1)
    return surge


def pm25_target(df: pd.DataFrame) -> pd.Series:
    """PM2.5 concentration from features table."""
    if "pm25_obs" in df.columns:
        return df["pm25_obs"].ffill().bfill().clip(0, 500)
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
        "exog_keys": ["prcp_sum", "rh_mean", "t2m_max", "heat_index",
                       "dengue_search", "respiratory_search"],
        "normalize": True,
    },
    "surge": {
        "fn": surge_target,
        "exog_keys": ["heat_index", "pm25_obs", "t2m_max", "rh_mean",
                       "heatstroke_search", "hospital_search"],
        "normalize": True,
    },
    "pm25": {
        "fn": pm25_target,
        "exog_keys": ["wind_max", "t2m_max", "rh_mean", "prcp_sum"],
        "normalize": False,
    },
}
