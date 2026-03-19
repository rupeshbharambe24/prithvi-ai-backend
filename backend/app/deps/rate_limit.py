from __future__ import annotations

import time
from typing import Callable

import redis
from fastapi import Depends, HTTPException, Request

from ..config import get_settings


_redis_client: redis.Redis | None = None
_local_counts: dict[str, int] = {}


def _get_redis_sync() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client


def rate_limiter_dep(limit_per_minute: int | None = None) -> Callable:
    settings = get_settings()
    limit = limit_per_minute or settings.rate_limit_per_minute

    async def limiter(request: Request):
        # Remote IP (behind reverse proxy could use X-Forwarded-For)
        ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
        now_min = int(time.time() // 60)
        key = f"rate:{ip}:{now_min}:{request.url.path}"
        if settings.local_mode or settings.redis_url.startswith("memory://"):
            current = _local_counts.get(key, 0) + 1
            _local_counts[key] = current
            if current > limit:
                raise HTTPException(status_code=429, detail="Too Many Requests")
            return
        r = _get_redis_sync()
        current = r.incr(key)
        if current == 1:
            r.expire(key, 60)
        if current > limit:
            raise HTTPException(status_code=429, detail="Too Many Requests")

    return limiter
