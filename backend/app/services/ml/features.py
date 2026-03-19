from __future__ import annotations

import numpy as np
import pandas as pd


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["doy"] = out.index.dayofyear
    out["dow"] = out.index.dayofweek
    out["sin_doy"] = np.sin(2 * np.pi * out["doy"] / 365.0)
    out["cos_doy"] = np.cos(2 * np.pi * out["doy"] / 365.0)
    for d in range(7):
        out[f"dow_{d}"] = (out["dow"] == d).astype(int)
    return out


def add_lags_rollings(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        for lag in [1, 3, 7, 14, 28]:
            out[f"{c}_lag{lag}"] = out[c].shift(lag)
        for w in [3, 7, 14]:
            out[f"{c}_roll{w}"] = out[c].rolling(window=w, min_periods=1).mean()
    return out

