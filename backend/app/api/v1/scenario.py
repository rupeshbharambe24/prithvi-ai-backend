from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import require_roles
from ...deps import csrf_protect
from ...db.models.user import UserRole
from ...db.session import get_db
from ...services.scenarios.runner import run_scenario
from ...services.runtime_state import create_job, update_job
from ...config import get_settings
from ...workers.celery_app import celery_app


router = APIRouter(prefix="/scenario", tags=["scenario"])


@router.post("/run", dependencies=[Depends(csrf_protect)])
async def scenario_run(payload: dict, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    # inline execution for simplicity; also enqueue background version
    res = await run_scenario(db, payload)
    return {"delta": res.delta, "ci": res.ci, "assumptions": res.assumptions, "costEstimate": res.costEstimate, "effectivenessScore": res.effectivenessScore, "coeffSource": res.coeffSource}


@router.post("/run/job", dependencies=[Depends(csrf_protect)])
async def scenario_run_job(payload: dict, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if settings.local_mode:
        job_id = create_job()
        update_job(job_id, status="running", progress=0.5)
        res = await run_scenario(db, payload)
        update_job(
            job_id,
            status="completed",
            progress=1.0,
            result={"delta": res.delta, "ci": res.ci, "assumptions": res.assumptions, "costEstimate": res.costEstimate, "effectivenessScore": res.effectivenessScore},
        )
        return {"jobId": job_id}
    async_result = celery_app.send_task("backend.app.workers.tasks_ops.scenario_run", kwargs={"payload": payload})
    return {"jobId": async_result.id}
