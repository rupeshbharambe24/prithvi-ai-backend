from __future__ import annotations

from typing import Callable

from starlette.requests import Request
from starlette.responses import Response


def security_headers_middleware() -> Callable:
    async def middleware(request: Request, call_next: Callable):
        response: Response = await call_next(request)
        csp = "default-src 'self'"
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    return middleware
