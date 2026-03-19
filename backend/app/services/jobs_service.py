from __future__ import annotations

import json
import threading
import uuid
import redis

from ..config import get_settings
from ..workers.celery_app import celery_app
from .runtime_state import create_job, get_job, run_demo_job


def _redis_sync() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def start_demo_long_job(total_steps: int = 20) -> str:
    settings = get_settings()
    if settings.local_mode or settings.redis_url.startswith("memory://"):
        job_id = create_job()
        thread = threading.Thread(target=run_demo_job, args=(job_id, total_steps), daemon=True)
        thread.start()
        return job_id
    job_id = uuid.uuid4().hex
    async_result = celery_app.send_task(
        "backend.app.workers.tasks.demo_long_job",
        kwargs={"job_id": job_id, "total_steps": total_steps},
    )
    r = _redis_sync()
    r.setex(f"job:{job_id}:task_id", 86400, async_result.id)
    r.hset(f"job:{job_id}:status", mapping={"status": "queued", "progress": 0})
    return job_id


def get_job_status(job_id: str) -> dict:
    settings = get_settings()
    if settings.local_mode or settings.redis_url.startswith("memory://"):
        return get_job(job_id)
    r = _redis_sync()
    data = r.hgetall(f"job:{job_id}:status")
    if not data:
        return {"status": "unknown"}
    try:
        progress = float(data.get("progress", 0))
    except Exception:
        progress = 0.0
    resp: dict = {"status": data.get("status", "unknown"), "progress": progress}
    if "result" in data:
        try:
            resp["result"] = json.loads(data["result"])  # type: ignore[assignment]
        except Exception:
            pass
    return resp
