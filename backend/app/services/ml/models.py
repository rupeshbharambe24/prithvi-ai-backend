from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor, LinearRegression, LogisticRegression


@dataclass
class FittedModel:
    algo: str
    model: Any
    q05: Any | None = None
    q95: Any | None = None


def _gb(params: Dict[str, Any] | None = None) -> GradientBoostingRegressor:
    params = params or {"n_estimators": 100, "max_depth": 2, "learning_rate": 0.1}
    return GradientBoostingRegressor(**params)


def fit_regression_with_quantiles(X: pd.DataFrame, y: pd.Series) -> FittedModel:
    base = _gb()
    base.fit(X, y)
    q05 = GradientBoostingRegressor(loss="quantile", alpha=0.05, **{"n_estimators": 80, "max_depth": 2, "learning_rate": 0.1})
    q95 = GradientBoostingRegressor(loss="quantile", alpha=0.95, **{"n_estimators": 80, "max_depth": 2, "learning_rate": 0.1})
    q05.fit(X, y)
    q95.fit(X, y)
    return FittedModel(algo="GBR", model=base, q05=q05, q95=q95)


def predict_with_uncertainty(fm: FittedModel, X: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    yhat = fm.model.predict(X)
    p05 = fm.q05.predict(X) if fm.q05 is not None else yhat - 0.2 * np.abs(yhat)
    p95 = fm.q95.predict(X) if fm.q95 is not None else yhat + 0.2 * np.abs(yhat)
    p05 = np.minimum(p05, yhat)
    p95 = np.maximum(p95, yhat)
    return yhat, p05, p95


def fit_poisson_glm(X: pd.DataFrame, y: pd.Series) -> Any:
    m = PoissonRegressor(max_iter=1000)
    m.fit(X, y)
    return m


def baseline_persistence(y: pd.Series) -> float:
    return float(y.iloc[-1]) if len(y) else 0.0


def baseline_seasonal_naive(y: pd.Series, period: int = 7) -> float:
    if len(y) > period:
        return float(y.iloc[-period])
    return float(y.mean()) if len(y) else 0.0

