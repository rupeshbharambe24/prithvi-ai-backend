from __future__ import annotations

import json
import time
import redis

from ..config import get_settings


_local_cache: dict[str, tuple[float, list[dict]]] = {}


def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def cache_get_series(key: str) -> list[dict] | None:
    settings = get_settings()
    if settings.local_mode or settings.redis_url.startswith("memory://"):
        cached = _local_cache.get(key)
        if not cached:
            return None
        expires_at, data = cached
        if expires_at < time.time():
            _local_cache.pop(key, None)
            return None
        return data
    r = _redis()
    data = r.get(key)
    if not data:
        return None
    return json.loads(data)


def cache_set_series(key: str, points: list[dict]) -> None:
    ttl = int(get_settings().cache_ttl_seconds)
    settings = get_settings()
    if settings.local_mode or settings.redis_url.startswith("memory://"):
        _local_cache[key] = (time.time() + ttl, points)
        return
    r = _redis()
    r.setex(key, ttl, json.dumps(points, default=str))
