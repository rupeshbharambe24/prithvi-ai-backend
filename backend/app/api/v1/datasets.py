from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.session import get_db
from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...models.datasets import DatasetOut, DatasetLineage
from ...services.catalog_service import list_datasets, dataset_lineage


router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("/", response_model=list[DatasetOut])
async def datasets(
    _user=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)
):
    dss = await list_datasets(db)
    return [DatasetOut.model_validate(ds) for ds in dss]


@router.get("", response_model=list[DatasetOut], include_in_schema=False)
async def datasets_noslash(
    _user=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)
):
    return await datasets(_user, db)


@router.get("/{dataset_id}/lineage", response_model=DatasetLineage)
async def lineage(
    dataset_id: int,
    _user=Depends(require_roles(UserRole.VIEWER)),
    db: AsyncSession = Depends(get_db),
):
    data = await dataset_lineage(db, dataset_id)
    if not data:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset = DatasetOut.model_validate(data["dataset"])
    return DatasetLineage(dataset=dataset, versions=data["versions"], ingest_runs=data["recent_runs"])  # type: ignore
