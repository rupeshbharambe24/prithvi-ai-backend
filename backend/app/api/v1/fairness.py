from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import require_roles
from ...deps import csrf_protect
from ...db.models.user import UserRole
from ...db.session import get_db
from ...services.qa.fairness import evaluate_heat_fairness
from ...services.qa.drift import compute_drift


router = APIRouter(prefix="/fairness", tags=["fairness"])


@router.post("/evaluate", dependencies=[Depends(csrf_protect)])
async def fairness_eval(target: str = "heat", regionId: int | None = None, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    if target == "heat":
        res = await evaluate_heat_fairness(db, region_id=regionId)
    else:
        res = await evaluate_heat_fairness(db, region_id=regionId)
    return res


@router.get("/latest")
async def fairness_latest(target: str = "heat", regionId: int | None = None, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, desc
    from ...db.models import FairnessReport
    res = await db.execute(select(FairnessReport).order_by(desc(FairnessReport.created_at)).limit(1))
    fr = res.scalars().first()
    if not fr:
        return {}
    metrics = fr.metrics_json or {}
    return {"reportId": fr.id, "metrics": metrics, "groups": metrics.get("groups", [])}


qa_router = APIRouter(prefix="/qa", tags=["qa"])


@qa_router.post("/drift", dependencies=[Depends(csrf_protect)])
async def drift(featureKey: str, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    res = await compute_drift(db, featureKey)
    return res


@qa_router.get("/drift/latest")
async def drift_latest(featureKey: str, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, desc
    from ...db.models import DriftReport
    res = await db.execute(select(DriftReport).where(DriftReport.feature_key == featureKey).order_by(desc(DriftReport.created_at)).limit(1))
    dr = res.scalars().first()
    if not dr:
        return {}
    m = dr.metrics_json or {}
    return {"reportId": dr.id, **m}
