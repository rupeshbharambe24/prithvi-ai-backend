from __future__ import annotations

from ..config import get_settings


def build_cors_middleware() -> dict:
    settings = get_settings()
    # Combine explicit origins list and legacy single origin, deduped
    origins = set(settings.cors_origins + [settings.frontend_origin]) if settings.frontend_origin else set(settings.cors_origins)
    allow_origins = sorted(list(origins)) if origins else [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
    ]
    # Explicit headers ensure preflight accepts CSRF + request id + auth
    allow_headers = [
        "Content-Type",
        "X-CSRF-Token",
        "X-Request-ID",
        "Authorization",
    ]
    return dict(
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=allow_headers,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
