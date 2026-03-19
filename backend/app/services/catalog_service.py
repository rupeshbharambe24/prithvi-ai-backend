from __future__ import annotations

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Dataset, DatasetVersion, IngestRun


async def list_datasets(db: AsyncSession) -> list[Dataset]:
    res = await db.execute(select(Dataset))
    return list(res.scalars())


async def dataset_lineage(db: AsyncSession, dataset_id: int) -> dict:
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        return {}
    vers_res = await db.execute(
        select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(desc(DatasetVersion.created_at)).limit(10)
    )
    runs_res = await db.execute(
        select(IngestRun).where(IngestRun.dataset_id == dataset_id).order_by(desc(IngestRun.started_at)).limit(3)
    )
    return {
        "dataset": ds,
        "versions": [
            {
                "id": v.id,
                "version": v.version,
                "coverage_start": v.coverage_start,
                "coverage_end": v.coverage_end,
                "created_at": v.created_at,
            }
            for v in vers_res.scalars()
        ],
        "recent_runs": [
            {
                "id": r.id,
                "status": r.status,
                "rows": r.rows,
                "started_at": r.started_at,
                "ended_at": r.ended_at,
            }
            for r in runs_res.scalars()
        ],
    }

