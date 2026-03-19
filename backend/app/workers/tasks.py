from __future__ import annotations

import json
import time
from typing import Any

import redis

from .celery_app import celery_app
from ..config import get_settings


def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


@celery_app.task(name="backend.app.workers.tasks.demo_long_job")
def demo_long_job(job_id: str, total_steps: int = 20) -> dict[str, Any]:
    r = _redis()
    channel = f"jobs:{job_id}"
    for step in range(1, total_steps + 1):
        progress = step / total_steps
        payload = {"jobId": job_id, "step": step, "total": total_steps, "progress": progress}
        r.hset(f"job:{job_id}:status", mapping={"status": "running", "progress": progress})
        r.publish(channel, json.dumps(payload))
        time.sleep(0.3)
    result = {"ok": True}
    r.hset(
        f"job:{job_id}:status",
        mapping={"status": "completed", "progress": 1.0, "result": json.dumps(result)},
    )
    r.publish(channel, json.dumps({"jobId": job_id, "status": "completed", "progress": 1.0}))
    return result

