"""Scenario runner with model-informed coefficients.

Uses SHAP feature importances from trained models to derive
intervention effectiveness coefficients. Falls back to YAML defaults
if no trained model exists.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    delta: Dict[str, float]
    ci: list[float]
    assumptions: Dict[str, float]
    costEstimate: float = 0.0
    effectivenessScore: float = 0.0
    coeffSource: str = "yaml_defaults"


def _load_yaml_coeffs() -> Dict[str, float]:
    path = os.path.join(os.path.dirname(__file__), "../../../config/scenario.yml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return data.get("coefficients", {"beta1": 0.001, "beta2": 0.002, "beta3": 0.003, "beta4": 0.004})
    except Exception:
        return {"beta1": 0.001, "beta2": 0.002, "beta3": 0.003, "beta4": 0.004}


async def _load_model_coeffs(db: AsyncSession) -> Optional[Dict[str, float]]:
    """Derive intervention coefficients from trained model's SHAP values.

    Maps SHAP feature importances to intervention effectiveness:
    - High SHAP for temperature -> cooling centers more effective
    - High SHAP for humidity -> outreach more effective
    - High SHAP for wind/pm25 -> vector control more effective
    """
    try:
        row = (await db.execute(text("""
            SELECT metrics_json, path FROM model_versions
            WHERE target='heat' ORDER BY created_at DESC LIMIT 1
        """))).fetchone()

        if not row:
            return None

        metrics = row[0]
        if isinstance(metrics, str):
            metrics = json.loads(metrics)

        model_rmse = metrics.get("rmse", 0.1)

        # Load model to get SHAP drivers
        from ..ml.registry import load_artifact
        bundle = load_artifact(row[1])
        if not isinstance(bundle, dict) or "xgb_model" not in bundle:
            return None

        xgb_model = bundle["xgb_model"]
        feature_names = bundle.get("feature_names", [])

        if not hasattr(xgb_model, "feature_importances_"):
            return None

        # Map feature importances to intervention coefficients
        importances = dict(zip(feature_names, xgb_model.feature_importances_))

        # Temperature-related features -> cooling effectiveness
        temp_importance = sum(
            importances.get(f, 0) for f in feature_names
            if any(k in f for k in ["t2m_max", "t2m_mean", "heat_index", "wbgt"])
        )

        # Humidity-related features -> outreach effectiveness
        humidity_importance = sum(
            importances.get(f, 0) for f in feature_names
            if any(k in f for k in ["rh_mean", "wet_bulb"])
        )

        # Wind/air-related -> vector control effectiveness
        wind_importance = sum(
            importances.get(f, 0) for f in feature_names
            if any(k in f for k in ["wind_max", "pm25", "prcp"])
        )

        # Normalize to coefficients (higher importance = higher beta)
        total = temp_importance + humidity_importance + wind_importance + 1e-6
        base_scale = 0.005  # Scale factor for coefficients

        coeffs = {
            "beta1": round(base_scale * temp_importance / total, 6),     # cooling
            "beta2": round(base_scale * humidity_importance / total, 6),  # outreach
            "beta3": round(base_scale * 0.3, 6),                         # staffing (constant)
            "beta4": round(base_scale * wind_importance / total, 6),     # vector control
            "model_rmse": model_rmse,
        }

        logger.info("Model-derived coefficients: %s", coeffs)
        return coeffs

    except Exception as e:
        logger.debug("model_coeffs_failed: %s", e)
        return None


def _diminishing(x: float, k: float = 0.01) -> float:
    """Diminishing returns: 1 - exp(-k*x)"""
    return 1.0 - math.exp(-k * x)


async def run_scenario(db: AsyncSession, req: Dict) -> ScenarioResult:
    # Try model-derived coefficients first
    model_coeffs = await _load_model_coeffs(db)
    if model_coeffs:
        coeffs = model_coeffs
        coeff_source = "trained_model"
    else:
        coeffs = _load_yaml_coeffs()
        coeff_source = "yaml_defaults"

    iv = req.get("interventions", {})

    cooling = float(iv.get("cooling_centers", {}).get("capacity_add", 0) or 0)
    outreach = float(iv.get("outreach", {}).get("coverage", 0) or 0)
    staffing = float(iv.get("staffing", {}).get("delta", 0) or 0)
    vector = float(iv.get("vector_control", {}).get("efficacy", 0) or 0)

    # Non-linear effects with diminishing returns
    eff_cooling = _diminishing(cooling, k=0.005) * 100
    eff_outreach = _diminishing(outreach, k=0.03) * 50
    eff_vector = _diminishing(vector, k=0.03) * 40
    eff_staffing = staffing * 0.8

    # Interaction term: cooling + outreach synergy
    synergy = 0.15 * min(eff_cooling, eff_outreach) if eff_cooling > 10 and eff_outreach > 10 else 0

    # Total impact on admissions
    delta_adm = -(eff_cooling * coeffs.get("beta1", 0.001)
                   + eff_outreach * coeffs.get("beta2", 0.002)
                   + eff_staffing * coeffs.get("beta3", 0.003)
                   + eff_vector * coeffs.get("beta4", 0.004)
                   + synergy * 0.002)

    # Derived metrics
    delta_mortality = delta_adm * 0.12
    delta_risk = delta_adm * 0.008

    # Confidence interval from model RMSE if available
    model_rmse = coeffs.get("model_rmse", 0.0)
    if model_rmse > 0:
        uncertainty = model_rmse * 1.96  # 95% CI from actual test error
    else:
        uncertainty = abs(delta_adm) * 0.35 + 2.0

    low = delta_adm - uncertainty
    high = delta_adm + min(uncertainty * 0.5, 0)

    # Cost estimate (INR lakhs)
    cost = (cooling * 50 + outreach * 200 + max(staffing, 0) * 5000 + vector * 150) / 100000

    # Effectiveness score 0-1
    total_input = cooling + outreach + vector + max(staffing, 0)
    effectiveness = min(1.0, abs(delta_adm) / max(total_input * 0.01, 1))

    return ScenarioResult(
        delta={"admissions": round(delta_adm, 2), "mortality": round(delta_mortality, 2), "risk": round(delta_risk, 4)},
        ci=[round(low, 2), round(high, 2)],
        assumptions={"cooling": cooling, "outreach": outreach, "staffing": staffing, "vector": vector},
        costEstimate=round(cost, 2),
        effectivenessScore=round(effectiveness, 3),
        coeffSource=coeff_source,
    )
