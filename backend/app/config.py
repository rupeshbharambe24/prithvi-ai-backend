from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv


load_dotenv()


def _raw_database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def _infer_local_mode() -> bool:
    raw_local = os.getenv("LOCAL_MODE")
    if raw_local is not None:
        return raw_local.lower() == "true"
    return True


def _resolved_database_url() -> str:
    raw_db = _raw_database_url()
    if _infer_local_mode():
        if raw_db.startswith("sqlite"):
            return raw_db
        return "sqlite+aiosqlite:///./prithvi.db"
    return raw_db or "postgresql+asyncpg://postgres:postgres@localhost:5432/app"


class Settings(BaseModel):
    local_mode: bool = Field(default=_infer_local_mode())
    env: str = Field(default=os.getenv("ENV", "development"))
    app_name: str = Field(default=os.getenv("APP_NAME", "prithvi-ai"))
    api_version: str = Field(default=os.getenv("API_VERSION", "v1"))

    host: str = Field(default=os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default=int(os.getenv("PORT", "8000")))

    database_url: str = Field(default=_resolved_database_url())
    redis_url: str = Field(default=os.getenv("REDIS_URL", "memory://local"))

    s3_endpoint: str = Field(default=os.getenv("S3_ENDPOINT", ""))
    s3_access_key: str = Field(default=os.getenv("S3_ACCESS_KEY", ""))
    s3_secret_key: str = Field(default=os.getenv("S3_SECRET_KEY", ""))
    s3_bucket: str = Field(default=os.getenv("S3_BUCKET", ""))

    secret_key: str = Field(default=os.getenv("SECRET_KEY", "change_me"))
    jwt_issuer: str = Field(default=os.getenv("JWT_ISSUER", "prithvi-ai"))
    jwt_audience: str = Field(default=os.getenv("JWT_AUDIENCE", "prithvi-clients"))
    jwt_access_ttl: int = Field(default=int(os.getenv("JWT_ACCESS_TTL", "900")))
    jwt_refresh_ttl: int = Field(default=int(os.getenv("JWT_REFRESH_TTL", "604800")))

    cors_origins_raw: str = Field(default=os.getenv("CORS_ORIGINS", ""))
    frontend_origin: str = Field(default=os.getenv("FRONTEND_ORIGIN", "http://localhost:3000"))
    cookie_secure: bool = Field(
        default=os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )

    sentry_dsn: str = Field(default=os.getenv("SENTRY_DSN", ""))
    otel_exporter_otlp_endpoint: str = Field(default=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))

    # Real data pipeline settings
    openaq_api_key: str = Field(default=os.getenv("OPENAQ_API_KEY", ""))
    ml_artifacts_root: str = Field(default=os.getenv("ML_ARTIFACTS_ROOT", "./ml_artifacts"))
    open_meteo_rate_limit: int = Field(default=int(os.getenv("OPEN_METEO_RATE_LIMIT", "10000")))

    rate_limit_per_minute: int = Field(default=int(os.getenv("RATE_LIMIT_PER_MINUTE", os.getenv("RATE_LIMIT_PER_MIN", "60"))))
    auth_rate_limit_per_minute: int = Field(
        default=int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10"))
    )
    cache_ttl_seconds: int = Field(default=int(os.getenv("CACHE_TTL_SECONDS", "300")))

    @property
    def cors_origins(self) -> List[str]:
        if not self.cors_origins_raw:
            return []
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
