from __future__ import annotations

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: str
    db: bool
    redis: bool
    objectStore: bool
    version: str
    uptimeSeconds: float


class JobCreated(BaseModel):
    jobId: str


class JobStatus(BaseModel):
    status: str
    progress: float | None = None
    result: dict | None = None
