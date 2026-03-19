from __future__ import annotations

from fastapi import APIRouter, Depends

from ...deps import csrf_protect
from ...models.common import JobCreated, JobStatus
from ...services.jobs_service import get_job_status, start_demo_long_job


router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/long-job", response_model=JobCreated, status_code=202, dependencies=[Depends(csrf_protect)])
async def long_job() -> JobCreated:
    job_id = start_demo_long_job(total_steps=20)
    return JobCreated(jobId=job_id)


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def job_status(job_id: str) -> JobStatus:
    data = get_job_status(job_id)
    return JobStatus(**data)


# Alias generic jobs route
@router.get("/../jobs/{job_id}", include_in_schema=False)
async def job_status_alias(job_id: str):
    return await job_status(job_id)
