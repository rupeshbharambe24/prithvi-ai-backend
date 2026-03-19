from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db
from ...db.models import ModelVersion, BacktestScore


router = APIRouter(prefix="/models", tags=["models"])


@router.get("/registry")
async def registry(target: str, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(ModelVersion).where(ModelVersion.target == target).order_by(desc(ModelVersion.created_at)))
    out = []
    for mv in res.scalars():
        out.append({
            "id": mv.id,
            "target": mv.target,
            "algo": mv.algo,
            "params": mv.params_json,
            "createdAt": mv.created_at.isoformat(),
            "path": mv.path,
            "metrics": mv.metrics_json,
        })
    return out


@router.get("/scores")
async def scores(target: str, regionId: int, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(BacktestScore).where(BacktestScore.target == target, BacktestScore.region_id == regionId).order_by(desc(BacktestScore.window_end)).limit(1))
    s = res.scalars().first()
    return s.metrics_json if s else {}

