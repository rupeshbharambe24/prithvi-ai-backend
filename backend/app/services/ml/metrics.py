from __future__ import annotations

import numpy as np


def rmse(y_true, y_pred) -> float:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mae(y_true, y_pred) -> float:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return float(np.mean(np.abs(y_true - y_pred)))


def pinball_loss(y_true, y_pred, tau: float) -> float:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    diff = y_true - y_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1) * diff)))


def crps_like(y_true, p05, p95, y_pred) -> float:
    # crude: average pinball at two quantiles
    return 0.5 * (pinball_loss(y_true, p05, 0.05) + pinball_loss(y_true, p95, 0.95))

