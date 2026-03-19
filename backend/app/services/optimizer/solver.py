"""Resource allocation optimizer.

Uses risk-proportional allocation: regions with higher forecast risk
get proportionally more resources. This replaces the naive equal
distribution approach.
"""
from __future__ import annotations

from typing import Dict, List


def solve(inputs: Dict) -> Dict:
    regions = inputs.get("regions", [])
    total_staff = int(inputs.get("resources", {}).get("staff", 10))
    constraints = inputs.get("constraints", {})
    min_per_region = int(constraints.get("min_staff_per_region", 1))

    n = max(1, len(regions))

    if not regions:
        return {"allocations": [], "objective": 0.0, "constraintsSatisfied": True}

    # Extract risk scores from region data
    risk_scores = []
    for r in regions:
        # Try to get risk from various fields
        risk = r.get("risk", r.get("heatRisk", r.get("forecast_risk", 0.5)))
        if isinstance(risk, (list, dict)):
            risk = 0.5
        risk_scores.append(max(0.01, float(risk)))

    # Normalize risk scores to get allocation weights
    total_risk = sum(risk_scores)
    weights = [rs / total_risk for rs in risk_scores]

    # Allocate: minimum per region first, then distribute remainder by risk
    allocated = [min_per_region] * n
    remaining = total_staff - sum(allocated)

    if remaining < 0:
        # Not enough for minimum — scale down
        for i in range(n):
            allocated[i] = max(1, total_staff // n)
        remaining = 0

    # Distribute remaining by risk weight
    if remaining > 0:
        for _ in range(remaining):
            # Find region with highest unmet need (weight - current allocation proportion)
            need = []
            current_total = sum(allocated)
            for i in range(n):
                current_prop = allocated[i] / max(current_total, 1)
                need.append(weights[i] - current_prop)
            best = need.index(max(need))
            allocated[best] += 1

    # Compute objective: weighted risk reduction
    objective = sum(a * w for a, w in zip(allocated, weights))

    alloc = []
    for i, r in enumerate(regions):
        alloc.append({
            "regionId": r.get("id"),
            "staff": allocated[i],
            "riskScore": round(risk_scores[i], 4),
            "weight": round(weights[i], 4),
            "notes": "risk-proportional",
        })

    constraints_met = all(a >= min_per_region for a in allocated)

    return {
        "allocations": alloc,
        "objective": round(objective, 4),
        "constraintsSatisfied": constraints_met,
        "method": "risk-proportional",
    }
