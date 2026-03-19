from __future__ import annotations

import os
from celery import Celery

from ..config import get_settings


settings = get_settings()

celery_app = Celery(
    "prithvi_ai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.app.workers.tasks", "backend.app.workers.tasks_models"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)
