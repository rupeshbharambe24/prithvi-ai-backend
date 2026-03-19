from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict

import redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from .celery_app import celery_app
from ..db.session import AsyncSessionLocal
from ..config import get_settings
from ..services.scenarios.runner import run_scenario
from ..services.optimizer.solver import solve
from ..services.alerts.engine import evaluate_rules


def _progress(job_id: str, payload: Dict):
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    r.publish(f"jobs:{job_id}", json.dumps(payload))


@celery_app.task(name="backend.app.workers.tasks_ops.scenario_run")
def scenario_run(payload: dict) -> Dict:
    async def _run() -> Dict:
        async with AsyncSessionLocal() as db:
            job_id = scenario_run.request.id  # type: ignore[attr-defined]
            r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
            r.hset(f"job:{job_id}:status", mapping={"status": "running", "progress": 0})
            _progress(job_id, {"event": "job-progress", "step": 1, "total": 2, "progress": 0.5, "jobId": job_id})
            res = await run_scenario(db, payload)
            _progress(job_id, {"event": "job-progress", "step": 2, "total": 2, "progress": 1.0, "jobId": job_id})
            r.hset(f"job:{job_id}:status", mapping={"status": "completed", "progress": 1.0, "result": json.dumps({"delta": res.delta})})
            return {"delta": res.delta, "ci": res.ci, "assumptions": res.assumptions}

    import asyncio

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(name="backend.app.workers.tasks_ops.optimizer_run")
def optimizer_run(payload: dict) -> Dict:
    job_id = optimizer_run.request.id  # type: ignore[attr-defined]
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    r.hset(f"job:{job_id}:status", mapping={"status": "running", "progress": 0})
    _progress(job_id, {"event": "job-progress", "step": 1, "total": 1, "progress": 0.5, "jobId": job_id})
    res = solve(payload)
    _progress(job_id, {"event": "job-progress", "step": 1, "total": 1, "progress": 1.0, "jobId": job_id})
    r.hset(f"job:{job_id}:status", mapping={"status": "completed", "progress": 1.0, "result": json.dumps(res)})
    return res


@celery_app.task(name="backend.app.workers.tasks_ops.alerts_run")
def alerts_run() -> Dict:
    async def _run() -> Dict:
        async with AsyncSessionLocal() as db:
            res = await evaluate_rules(db)
            return res

    import asyncio

    return asyncio.get_event_loop().run_until_complete(_run())


@celery_app.task(name="backend.app.workers.tasks_ops.retention_job")
def retention_job(days_forecasts: int = 30, days_alerts: int = 90) -> Dict:
    async def _run() -> Dict:
        async with AsyncSessionLocal() as db:
            cutoff_f = datetime.now(timezone.utc) - timedelta(days=days_forecasts)
            cutoff_a = datetime.now(timezone.utc) - timedelta(days=days_alerts)
            await db.execute(text("DELETE FROM forecasts WHERE created_at < :cut"), {"cut": cutoff_f})
            await db.execute(text("DELETE FROM alerts WHERE created_at < :cut"), {"cut": cutoff_a})
            await db.commit()
            return {"deleted": True}

    import asyncio

    return asyncio.get_event_loop().run_until_complete(_run())
