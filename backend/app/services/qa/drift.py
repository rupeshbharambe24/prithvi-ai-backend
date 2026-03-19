"""Real drift detection using PSI (Population Stability Index).

Compares feature distributions between reference and current windows
to detect data drift. Auto-creates alerts when drift is detected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...db.models import DriftReport

logger = logging.getLogger(__name__)

# PSI thresholds (standard industry practice)
PSI_THRESHOLD_WARNING = 0.1    # Moderate drift
PSI_THRESHOLD_CRITICAL = 0.25  # Significant drift


def _psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Compute Population Stability Index between two distributions."""
    if len(reference) < 5 or len(current) < 5:
        return 0.0

    # Create bins from reference distribution
    qs = np.linspace(0, 1, bins + 1)
    try:
        cuts = np.quantile(reference, qs)
        # Ensure unique bin edges
        cuts = np.unique(cuts)
        if len(cuts) < 3:
            return 0.0

        ref_hist, _ = np.histogram(reference, bins=cuts)
        cur_hist, _ = np.histogram(current, bins=cuts)

        # Add small epsilon to avoid division by zero
        eps = 1e-6
        ref_prob = (ref_hist + eps) / np.sum(ref_hist + eps)
        cur_prob = (cur_hist + eps) / np.sum(cur_hist + eps)

        psi = float(np.sum((cur_prob - ref_prob) * np.log(cur_prob / ref_prob)))
        return max(0.0, psi)
    except Exception:
        return 0.0


def _ks_statistic(reference: np.ndarray, current: np.ndarray) -> float:
    """Compute Kolmogorov-Smirnov statistic."""
    if len(reference) < 5 or len(current) < 5:
        return 0.0
    try:
        from scipy.stats import ks_2samp
        stat, p_value = ks_2samp(reference, current)
        return float(stat)
    except ImportError:
        # Manual KS: max difference between CDFs
        all_vals = np.sort(np.concatenate([reference, current]))
        ref_cdf = np.searchsorted(np.sort(reference), all_vals, side='right') / len(reference)
        cur_cdf = np.searchsorted(np.sort(current), all_vals, side='right') / len(current)
        return float(np.max(np.abs(ref_cdf - cur_cdf)))


async def compute_drift(db: AsyncSession, feature_key: str) -> Dict:
    """Compute drift metrics for a feature using reference vs current window.

    Reference: days -60 to -30
    Current: days -30 to now
    """
    now = datetime.now(timezone.utc)
    mid = now - timedelta(days=30)
    start = now - timedelta(days=60)

    # Get feature values
    res = await db.execute(text("""
        SELECT value, ts FROM features
        WHERE feature_key=:k AND ts BETWEEN :s AND :e
        ORDER BY ts
    """), {"k": feature_key, "s": start, "e": now})
    rows = res.fetchall()

    # Parse values (handle SQLite string storage)
    all_vals = []
    for r in rows:
        val = r[0]
        if isinstance(val, str):
            try:
                val = float(val.strip("[]"))
            except (ValueError, TypeError):
                continue
        all_vals.append((float(val), r[1]))

    if len(all_vals) < 10:
        psi = 0.0
        ks = 0.0
        drift_detected = False
    else:
        # Split into reference and current
        ref_vals = []
        cur_vals = []
        for val, ts in all_vals:
            ts_str = ts if isinstance(ts, str) else ts.isoformat() if hasattr(ts, 'isoformat') else str(ts)
            if ts_str < mid.isoformat():
                ref_vals.append(val)
            else:
                cur_vals.append(val)

        ref_arr = np.array(ref_vals) if ref_vals else np.array(all_vals[:len(all_vals)//2])
        cur_arr = np.array(cur_vals) if cur_vals else np.array(all_vals[len(all_vals)//2:])

        # Handle case where arrays are lists of tuples
        if ref_arr.ndim > 1:
            ref_arr = ref_arr[:, 0].astype(float)
        if cur_arr.ndim > 1:
            cur_arr = cur_arr[:, 0].astype(float)

        psi = _psi(ref_arr, cur_arr)
        ks = _ks_statistic(ref_arr, cur_arr)
        drift_detected = psi > PSI_THRESHOLD_WARNING

    # Summary statistics
    ref_mean = float(np.mean([v for v, _ in all_vals[:len(all_vals)//2]])) if all_vals else 0
    cur_mean = float(np.mean([v for v, _ in all_vals[len(all_vals)//2:]])) if all_vals else 0

    metrics = {
        "psi": round(psi, 6),
        "ks_statistic": round(ks, 6),
        "drift_detected": drift_detected,
        "drift_level": "critical" if psi > PSI_THRESHOLD_CRITICAL else "warning" if psi > PSI_THRESHOLD_WARNING else "none",
        "reference_mean": round(ref_mean, 4),
        "current_mean": round(cur_mean, 4),
        "referenceWindow": [start.isoformat(), mid.isoformat()],
        "currentWindow": [mid.isoformat(), now.isoformat()],
        "n_reference": len(all_vals) // 2,
        "n_current": len(all_vals) - len(all_vals) // 2,
    }

    dr = DriftReport(
        feature_key=feature_key,
        created_at=now,
        metrics_json=metrics,
    )
    db.add(dr)

    # Auto-create alert if drift detected
    if drift_detected:
        await _create_drift_alert(db, feature_key, psi, metrics["drift_level"])

    await db.commit()

    logger.info("Drift %s: PSI=%.4f KS=%.4f detected=%s",
                feature_key, psi, ks, drift_detected)

    return {"reportId": dr.id, **metrics}


async def compute_all_drift(db: AsyncSession) -> Dict:
    """Compute drift for all key features."""
    features = ["t2m_max", "t2m_mean", "rh_mean", "prcp_sum", "wind_max", "heat_index", "wbgt"]
    results = {}
    for fk in features:
        try:
            result = await compute_drift(db, fk)
            results[fk] = result
        except Exception as e:
            logger.warning("drift_%s_failed: %s", fk, e)
            results[fk] = {"psi": 0.0, "error": str(e)}
    return results


async def _create_drift_alert(db: AsyncSession, feature_key: str, psi: float, level: str) -> None:
    """Create an alert for detected data drift."""
    try:
        now = datetime.now(timezone.utc)
        await db.execute(text("""
            INSERT INTO alerts (rule_id, region_id, severity, payload, started_at, status)
            VALUES (
                (SELECT id FROM alert_rules LIMIT 1),
                (SELECT id FROM regions LIMIT 1),
                :severity,
                :payload,
                :now,
                'active'
            )
        """), {
            "severity": "critical" if level == "critical" else "warning",
            "payload": f'{{"type":"drift","feature":"{feature_key}","psi":{psi:.4f},"level":"{level}"}}',
            "now": now,
        })
    except Exception as e:
        logger.debug("drift_alert_creation_failed: %s", e)
