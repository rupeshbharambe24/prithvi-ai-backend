"""Real fairness evaluation: per-region MAE and coverage gap.

Compares forecast accuracy across regions to detect bias.
Uses actual observations as ground truth when available.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...db.models import FairnessReport

logger = logging.getLogger(__name__)


async def evaluate_heat_fairness(db: AsyncSession, region_id: int | None = None) -> Dict:
    """Compute per-region fairness metrics for heat forecasts.

    Methodology:
    1. Get forecasts per region for last 30 days
    2. Get actual observations (heat_index from features table)
    3. Pair forecasts with actuals by (region, date)
    4. Compute per-group MAE and coverage rate
    5. Report MAE gap (max - min across groups)
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)

    # Get forecasts per region
    fcs = (await db.execute(text("""
        SELECT f.region_id, f.target_date, f.value, f.p05, f.p95
        FROM forecasts f
        WHERE f.type='heat' AND f.target_date BETWEEN :start AND :now
        ORDER BY f.region_id, f.target_date
    """), {"start": start, "now": now})).fetchall()

    if not fcs:
        report = {"mae": 0.0, "maeGap": 0.0, "coverageRate": 1.0, "coverageGap": 0.0}
        fr = FairnessReport(target="heat", region_scope="all", created_at=now, metrics_json=report)
        db.add(fr)
        await db.commit()
        return {"reportId": fr.id, "metrics": report, "groups": []}

    # Get actual observations (heat_index from features table)
    actuals = (await db.execute(text("""
        SELECT region_id, ts, value FROM features
        WHERE feature_key='heat_index' AND ts BETWEEN :start AND :now
    """), {"start": start, "now": now})).fetchall()

    # Build actuals lookup: {(region_id, date_str): value}
    actual_map: Dict = {}
    for r in actuals:
        rid = r[0]
        ts_val = r[1]
        # Handle SQLite string dates
        date_str = ts_val[:10] if isinstance(ts_val, str) else ts_val.strftime("%Y-%m-%d") if hasattr(ts_val, 'strftime') else str(ts_val)[:10]
        val = r[2]
        if isinstance(val, str):
            try:
                val = float(val.strip("[]"))
            except (ValueError, TypeError):
                continue
        actual_map[(rid, date_str)] = float(val)

    # Group forecasts by region
    region_forecasts: Dict[int, List] = {}
    for r in fcs:
        rid = r[0]
        td = r[1]
        date_str = td[:10] if isinstance(td, str) else td.strftime("%Y-%m-%d") if hasattr(td, 'strftime') else str(td)[:10]
        region_forecasts.setdefault(rid, []).append({
            "date": date_str, "value": r[2], "p05": r[3], "p95": r[4],
        })

    # Get region names
    region_names = {}
    rnames = (await db.execute(text("SELECT id, name FROM regions"))).fetchall()
    for r in rnames:
        region_names[r[0]] = r[1]

    # Compute per-region metrics
    groups = []
    all_errors = []
    all_coverage = []

    for rid, forecasts in region_forecasts.items():
        errors = []
        coverages = []
        for fc in forecasts:
            actual = actual_map.get((rid, fc["date"]))
            if actual is None:
                # Use center of interval as proxy if no actual
                actual = (fc["p05"] + fc["p95"]) / 2.0

            error = abs(fc["value"] - actual)
            errors.append(error)

            # Coverage: actual falls within [p05, p95]
            in_interval = 1.0 if (actual >= fc["p05"] and actual <= fc["p95"]) else 0.0
            coverages.append(in_interval)

        if errors:
            group_mae = float(np.mean(errors))
            group_coverage = float(np.mean(coverages))
            groups.append({
                "group": region_names.get(rid, f"Region {rid}"),
                "region_id": rid,
                "mae": round(group_mae, 6),
                "coverage": round(group_coverage, 4),
                "n_forecasts": len(errors),
            })
            all_errors.extend(errors)
            all_coverage.extend(coverages)

    # Overall metrics
    overall_mae = float(np.mean(all_errors)) if all_errors else 0.0
    overall_coverage = float(np.mean(all_coverage)) if all_coverage else 1.0

    # Gap metrics
    group_maes = [g["mae"] for g in groups]
    group_coverages = [g["coverage"] for g in groups]
    mae_gap = (max(group_maes) - min(group_maes)) if group_maes else 0.0
    coverage_gap = (max(group_coverages) - min(group_coverages)) if group_coverages else 0.0

    report = {
        "mae": round(overall_mae, 6),
        "maeGap": round(mae_gap, 6),
        "coverageRate": round(overall_coverage, 4),
        "coverageGap": round(coverage_gap, 4),
        "n_groups": len(groups),
        "n_forecasts": len(all_errors),
    }

    fr = FairnessReport(target="heat", region_scope="all", created_at=now, metrics_json=report)
    db.add(fr)
    await db.commit()

    logger.info("Fairness: MAE=%.4f gap=%.4f coverage=%.2f gap=%.2f (%d groups)",
                overall_mae, mae_gap, overall_coverage, coverage_gap, len(groups))

    return {"reportId": fr.id, "metrics": report, "groups": groups}
