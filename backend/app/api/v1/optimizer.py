from __future__ import annotations

from fastapi import APIRouter, Depends

from ...deps.auth import require_roles
from ...deps import csrf_protect
from ...db.models.user import UserRole
from ...services.optimizer.solver import solve
from ...services.runtime_state import create_job, update_job
from ...config import get_settings
from ...workers.celery_app import celery_app


router = APIRouter(prefix="/optimizer", tags=["optimizer"])


@router.post("/run", dependencies=[Depends(csrf_protect)])
async def optimizer_run(payload: dict, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST))):
    settings = get_settings()
    if settings.local_mode:
        job_id = create_job()
        update_job(job_id, status="running", progress=0.5)
        res = solve(payload)
        update_job(job_id, status="completed", progress=1.0, result=res)
        return {"jobId": job_id}
    async_result = celery_app.send_task("backend.app.workers.tasks_ops.optimizer_run", kwargs={"payload": payload})
    return {"jobId": async_result.id}
