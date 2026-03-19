from __future__ import annotations

from fastapi import APIRouter

from ...models.common import JobStatus
from ...services.jobs_service import get_job_status


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobStatus)
async def job_status(job_id: str) -> JobStatus:
    data = get_job_status(job_id)
    return JobStatus(**data)

