from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from minio import Minio
import redis

from ...config import get_settings
from ...db.session import get_db
from ...models.common import HealthStatus
from ...deps import rate_limiter_dep


router = APIRouter(prefix="/health", tags=["health"])
_start_time = time.time()


@router.get("/", response_model=HealthStatus, dependencies=[Depends(rate_limiter_dep())])
async def health(db: AsyncSession = Depends(get_db)) -> HealthStatus:
    settings = get_settings()

    # DB
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    # Redis
    if settings.local_mode or settings.redis_url.startswith("memory://"):
        redis_ok = True
    else:
        try:
            r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            r.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    # Object store
    if settings.local_mode or not settings.s3_endpoint:
        object_store_ok = True
    else:
        try:
            client = Minio(
                endpoint=settings.s3_endpoint.replace("http://", "").replace("https://", ""),
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                secure=settings.s3_endpoint.startswith("https://"),
            )
            # Just try list buckets
            list(client.list_buckets())
            object_store_ok = True
        except Exception:
            object_store_ok = False

    uptime = time.time() - _start_time
    return HealthStatus(
        status="ok" if (db_ok and redis_ok and object_store_ok) else "degraded",
        db=db_ok,
        redis=redis_ok,
        objectStore=object_store_ok,
        version="0.1.0",
        uptimeSeconds=uptime,
    )


# Also support /api/health without trailing slash
@router.get("", response_model=HealthStatus, include_in_schema=False)
async def health_no_slash(db: AsyncSession = Depends(get_db)) -> HealthStatus:
    return await health(db)
