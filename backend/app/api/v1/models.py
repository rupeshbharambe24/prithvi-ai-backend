from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db
from ...db.models import ModelVersion, BacktestScore


router = APIRouter(prefix="/models", tags=["models"])


@router.get("/all")
async def all_models(_=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    """Return all model versions grouped for the model catalog page."""
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT id, target, algo, params_json, created_at, path, metrics_json FROM model_versions ORDER BY target, created_at DESC"
    ))).fetchall()
    regions = {r[0]: r[1] for r in (await db.execute(text("SELECT id, name FROM regions"))).fetchall()}
    import json as _json
    out = []
    for r in rows:
        metrics = r[6]
        if isinstance(metrics, str):
            try: metrics = _json.loads(metrics)
            except Exception: metrics = {}
        params = r[3]
        if isinstance(params, str):
            try: params = _json.loads(params)
            except Exception: params = {}
        # Infer region from path pattern: ./ml_artifacts/{target}/{timestamp}/model.joblib
        # Models are stored in order: region 1, 2, 3 per target
        path_str = r[5] or ""
        region_name = None
        for rid, rname in regions.items():
            if rname.lower() in path_str.lower():
                region_name = rname
                break
        out.append({
            "id": r[0], "target": r[1], "algo": r[2],
            "params": params, "metrics": metrics,
            "regionName": region_name,
            "createdAt": r[4].isoformat() if hasattr(r[4], 'isoformat') else str(r[4]),
        })
    # Assign regions by order within each target group (models created in region order 1,2,3)
    from itertools import groupby
    for _target, group in groupby(out, key=lambda x: x["target"]):
        items = list(group)
        region_list = list(regions.values())
        for i, item in enumerate(items):
            if not item["regionName"] and i < len(region_list):
                item["regionName"] = region_list[i]
    return out


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

