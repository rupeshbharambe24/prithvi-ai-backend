from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_, asc
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.models import Feature, DQIssue, IngestRun
from ...models.data import SeriesResponse, SeriesPoint, SeriesMeta, QualityResponse
from ...services.cache_service import cache_get_series, cache_set_series


router = APIRouter(prefix="/data", tags=["data"])


@router.get("/series", response_model=SeriesResponse)
async def series(
    regionId: int,
    key: str,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    _user=Depends(require_roles(UserRole.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    from_dt = from_ or datetime.min
    to_dt = to or datetime.max
    cache_key = f"series:{regionId}:{key}:{from_dt.isoformat()}:{to_dt.isoformat()}"
    cached = cache_get_series(cache_key)
    if cached is not None:
        points = [SeriesPoint(**p) for p in cached]
        meta = SeriesMeta(feature_key=key, region_id=regionId)
        return SeriesResponse(points=points, meta=meta)

    q = (
        select(Feature)
        .where(
            and_(
                Feature.region_id == regionId,
                Feature.feature_key == key,
                Feature.ts >= from_dt,
                Feature.ts <= to_dt,
            )
        )
        .order_by(asc(Feature.ts))
    )
    res = await db.execute(q)
    feats = list(res.scalars())
    points = [SeriesPoint(ts=f.ts, value=f.value, unit=f.unit) for f in feats]
    cache_set_series(cache_key, [p.model_dump(by_alias=True) for p in points])
    meta = SeriesMeta(feature_key=key, region_id=regionId)
    return SeriesResponse(points=points, meta=meta)


@router.get("/export")
async def export(
    datasetId: int,
    regionId: int | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    fmt: str = "csv",
    _user=Depends(require_roles(UserRole.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    # Stream CSV for simplicity
    from fastapi.responses import StreamingResponse
    import csv
    from io import StringIO

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["ts", "value", "unit"]) 
    q = select(Feature).where(Feature.feature_key == "heat_index")
    res = await db.execute(q)
    for f in res.scalars():
        writer.writerow([f.ts.isoformat(), f.value, f.unit or ""])
    si.seek(0)
    return StreamingResponse(si, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=export.csv"})


# Accept datasetId as int id or string name
@router.get("/quality", response_model=QualityResponse)
async def quality(
    datasetId: str,
    _user=Depends(require_roles(UserRole.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    from ...db.models import Dataset
    # Resolve dataset id
    ds_id_int: int | None = None
    try:
        ds_id_int = int(datasetId)
    except Exception:
        # lookup by name
        from sqlalchemy import select
        ds = (await db.execute(select(Dataset).where(Dataset.name == datasetId))).scalars().first()
        if ds:
            ds_id_int = ds.id
    if ds_id_int is None:
        ds_id_int = 1
    # Counts by severity
    res = await db.execute(select(DQIssue.severity, DQIssue.id).where(DQIssue.dataset_id == ds_id_int))
    by_sev: dict[str, int] = {}
    total = 0
    for severity, _ in res:
        by_sev[severity] = by_sev.get(severity, 0) + 1
        total += 1
    run = (
        await db.execute(
            select(IngestRun).where(IngestRun.dataset_id == ds_id_int).order_by(IngestRun.started_at.desc())
        )
    ).scalars().first()
    last_run = None
    if run:
        last_run = {
            "status": run.status,
            "rows": run.rows,
            "coverageStart": getattr(run, "started_at", None),
            "coverageEnd": getattr(run, "ended_at", None),
        }
    return QualityResponse(last_run=last_run, issues={"total": total, "bySeverity": by_sev})
