from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import redis.asyncio as aioredis

from ...config import get_settings


router = APIRouter(prefix="/events", tags=["events"])


async def _event_stream(request: Request, channels: list[str], patterns: list[str]) -> AsyncGenerator[bytes, None]:
    if get_settings().local_mode:
        while True:
            if await request.is_disconnected():
                break
            yield b"event: heartbeat\ndata: {\"mode\": \"local\"}\n\n"
            await asyncio.sleep(5)
        return
    r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    pubsub = r.pubsub()
    for ch in channels:
        await pubsub.subscribe(ch)
    for pat in patterns:
        await pubsub.psubscribe(pat)
    try:
        last_hb = 0.0
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") in {"message", "pmessage"}:
                data_raw = message.get("data")
                try:
                    data = json.loads(data_raw)
                except Exception:
                    data = {"raw": data_raw}
                ev_name = data.get("event") or "job-progress"
                if ev_name.startswith("alert"):
                    payload = (
                        f"event: {ev_name}\n"
                        f"data: {json.dumps(data)}\n\n"
                    )
                else:
                    payload = (
                        f"event: job-progress\n"
                        f"id: {data.get('jobId','')}:{data.get('step','')}\n"
                        f"data: {json.dumps(data)}\n\n"
                    )
                yield payload.encode("utf-8")
            else:
                # heartbeat every 10s
                last_hb += 0.5
                if last_hb >= 10.0:
                    hb = f"event: heartbeat\ndata: {{\"ts\": \"{json.dumps(str(asyncio.get_event_loop().time()))}\"}}\n\n"
                    yield hb.encode("utf-8")
                    last_hb = 0.0
                await asyncio.sleep(0.5)
    finally:
        for channel in channels:
            await pubsub.unsubscribe(channel)
        for pattern in patterns:
            await pubsub.punsubscribe(pattern)
        await pubsub.close()
        await r.close()


@router.get("/stream")
async def events_stream(request: Request, jobId: str | None = None):
    channels = ["alerts"]
    patterns = []
    if jobId:
        channels.append(f"jobs:{jobId}")
    else:
        patterns.append("jobs:*")
    generator = _event_stream(request, channels, patterns)
    return StreamingResponse(generator, media_type="text/event-stream")
