"""Resource allocation optimizer.

Uses scipy linear programming to optimally allocate resources across regions,
maximizing expected risk reduction subject to budget and minimum-staffing
constraints. Falls back to risk-proportional heuristic if scipy fails.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def _lp_solve(risk_scores: List[float], total_staff: int, min_per_region: int) -> List[int]:
    """Solve resource allocation as a linear program using scipy.

    Maximize: sum(risk_i * staff_i) — risk-weighted allocation
    Subject to:
        sum(staff_i) = total_staff
        staff_i >= min_per_region for all i
        staff_i >= 0
    """
    try:
        from scipy.optimize import linprog

        n = len(risk_scores)
        # linprog minimizes, so negate risk scores to maximize risk-weighted allocation
        c = [-r for r in risk_scores]

        # Equality constraint: sum(staff) = total_staff
        A_eq = [np.ones(n).tolist()]
        b_eq = [float(total_staff)]

        # Bounds: each region gets at least min_per_region
        bounds = [(float(min_per_region), float(total_staff)) for _ in range(n)]

        result = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")

        if result.success:
            # Round to integers using largest remainder method
            raw = result.x
            floored = [int(x) for x in raw]
            remainder = [raw[i] - floored[i] for i in range(n)]

            # Distribute remaining staff to regions with largest fractional parts
            remaining = total_staff - sum(floored)
            indices = sorted(range(n), key=lambda i: remainder[i], reverse=True)
            for i in range(min(remaining, n)):
                floored[indices[i]] += 1

            # Ensure minimums are met
            for i in range(n):
                if floored[i] < min_per_region:
                    floored[i] = min_per_region

            logger.info("LP optimization succeeded (method=highs)")
            return floored
        else:
            logger.warning("LP solver did not converge: %s", result.message)
            return []

    except ImportError:
        logger.warning("scipy not available for LP optimization")
        return []
    except Exception as e:
        logger.warning("LP optimization failed: %s", e)
        return []


def _greedy_fallback(risk_scores: List[float], total_staff: int, min_per_region: int) -> List[int]:
    """Greedy risk-proportional allocation as fallback."""
    n = len(risk_scores)
    total_risk = sum(risk_scores)
    weights = [rs / total_risk for rs in risk_scores]

    allocated = [min_per_region] * n
    remaining = total_staff - sum(allocated)

    if remaining < 0:
        for i in range(n):
            allocated[i] = max(1, total_staff // n)
        return allocated

    if remaining > 0:
        for _ in range(remaining):
            current_total = sum(allocated)
            need = [weights[i] - allocated[i] / max(current_total, 1) for i in range(n)]
            best = need.index(max(need))
            allocated[best] += 1

    return allocated


def solve(inputs: Dict) -> Dict:
    """Optimize resource allocation across regions.

    Uses scipy LP when available, falls back to greedy risk-proportional.
    """
    regions = inputs.get("regions", [])
    total_staff = int(inputs.get("resources", {}).get("staff", 10))
    constraints = inputs.get("constraints", {})
    min_per_region = int(constraints.get("min_staff_per_region", 1))

    n = max(1, len(regions))

    if not regions:
        return {"allocations": [], "objective": 0.0, "constraintsSatisfied": True, "method": "none"}

    # Extract risk scores
    risk_scores = []
    for r in regions:
        risk = r.get("risk", r.get("heatRisk", r.get("forecast_risk", 0.5)))
        if isinstance(risk, (list, dict)):
            risk = 0.5
        risk_scores.append(max(0.01, float(risk)))

    # Normalize risk scores
    total_risk = sum(risk_scores)
    weights = [rs / total_risk for rs in risk_scores]

    # Try LP first, fall back to greedy
    allocated = _lp_solve(risk_scores, total_staff, min_per_region)
    method = "scipy_lp"
    if not allocated:
        allocated = _greedy_fallback(risk_scores, total_staff, min_per_region)
        method = "greedy_proportional"

    # Compute objective: weighted risk reduction
    objective = sum(a * w for a, w in zip(allocated, weights))

    alloc = []
    for i, r in enumerate(regions):
        alloc.append({
            "regionId": r.get("id"),
            "staff": allocated[i],
            "riskScore": round(risk_scores[i], 4),
            "weight": round(weights[i], 4),
            "notes": method,
        })

    constraints_met = all(a >= min_per_region for a in allocated)

    return {
        "allocations": alloc,
        "objective": round(objective, 4),
        "constraintsSatisfied": constraints_met,
        "method": method,
    }
