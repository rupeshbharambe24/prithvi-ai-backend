from __future__ import annotations

import threading
import time
import uuid
from typing import Any


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(initial_status: str = "queued") -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"status": initial_status, "progress": 0.0}
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        current = _jobs.setdefault(job_id, {"status": "queued", "progress": 0.0})
        current.update(fields)


def get_job(job_id: str) -> dict[str, Any]:
    with _lock:
        data = _jobs.get(job_id)
        if not data:
            return {"status": "unknown"}
        return dict(data)


def run_background_job(target, *args, **kwargs) -> str:
    job_id = create_job()

    def _runner():
        try:
            result = target(job_id, *args, **kwargs)
            if result is not None:
                update_job(job_id, status="completed", progress=1.0, result=result)
            else:
                update_job(job_id, status="completed", progress=1.0)
        except Exception as exc:  # pragma: no cover
            update_job(job_id, status="failed", progress=1.0, result={"error": str(exc)})

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return job_id


def run_demo_job(job_id: str, total_steps: int = 20) -> None:
    update_job(job_id, status="running", progress=0.0)
    for step in range(1, total_steps + 1):
        time.sleep(0.2)
        update_job(job_id, status="running", progress=step / total_steps)
    update_job(job_id, status="completed", progress=1.0, result={"ok": True})
