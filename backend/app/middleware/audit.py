from __future__ import annotations

import time
import uuid
from starlette.requests import Request
from starlette.responses import Response

async def audit_middleware(request: Request, call_next):
    # Get header, or prior state, or generate a new one
    request_id = request.headers.get("X-Request-ID") or getattr(request.state, "request_id", None) or str(uuid.uuid4())
    request.state.request_id = request_id

    start_time = time.time()
    response: Response = await call_next(request)

    # Always include the request id in the response
    if "X-Request-ID" not in response.headers:
        response.headers["X-Request-ID"] = request_id
    return response
