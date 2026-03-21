from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

import sentry_sdk
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import structlog

from .config import get_settings
from .middleware.audit import audit_middleware
from .middleware.security_headers import security_headers_middleware
from .utils.logging import configure_logging
from .deps import build_cors_middleware
from .api.v1 import auth as auth_routes
from .api.v1 import health as health_routes
from .api.v1 import demo as demo_routes
from .api.v1 import events as events_routes
from .api.v1 import regions as regions_routes
from .api.v1 import datasets as datasets_routes
from .api.v1 import data as data_routes
from .api.v1 import tiles as tiles_routes
from .api.v1 import risk as risk_routes
from .api.v1 import hospital as hospital_routes
from .api.v1 import air as air_routes
from .api.v1 import models as models_routes
from .api.v1 import kg as kg_routes
from .api.v1 import evidence as evidence_routes
from .api.v1 import alerts as alerts_routes
from .api.v1 import governance as governance_routes
from .api.v1 import scenario as scenario_routes
from .api.v1 import optimizer as optimizer_routes
from .api.v1 import fairness as fairness_routes
from .api.v1.fairness import qa_router as qa_routes
from .api.v1 import jobs as jobs_routes
from .deps.auth import require_roles
from .db.models.user import UserRole
from .db.local_bootstrap import init_local_database
from minio import Minio


configure_logging()
logger = structlog.get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", openapi_url="/openapi.json")

    # Sentry
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)

    # OTel
    FastAPIInstrumentor.instrument_app(app)

    # Middleware: request id
    @app.middleware("http")
    async def add_request_id(request: Request, call_next: Callable):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    # Middleware: CORS first (so preflight is handled before other middlewares)
    app.add_middleware(CORSMiddleware, **build_cors_middleware())
    app.middleware("http")(security_headers_middleware())
    app.middleware("http")(audit_middleware)

    # Routes
    api_prefix = "/api"
    v1_prefix = f"{api_prefix}/{settings.api_version}"
    app.include_router(health_routes.router, prefix=v1_prefix)
    app.include_router(auth_routes.router, prefix=v1_prefix)
    app.include_router(demo_routes.router, prefix=v1_prefix)
    app.include_router(events_routes.router, prefix=v1_prefix)
    app.include_router(regions_routes.router, prefix=v1_prefix)
    app.include_router(datasets_routes.router, prefix=v1_prefix)
    app.include_router(data_routes.router, prefix=v1_prefix)
    app.include_router(tiles_routes.router, prefix="")
    app.include_router(risk_routes.router, prefix=v1_prefix)
    app.include_router(hospital_routes.router, prefix=v1_prefix)
    app.include_router(air_routes.router, prefix=v1_prefix)
    app.include_router(models_routes.router, prefix=v1_prefix)
    app.include_router(kg_routes.router, prefix=v1_prefix)
    app.include_router(evidence_routes.router, prefix=v1_prefix)
    app.include_router(alerts_routes.router, prefix=v1_prefix)
    app.include_router(governance_routes.router, prefix=v1_prefix)
    app.include_router(scenario_routes.router, prefix=v1_prefix)
    app.include_router(optimizer_routes.router, prefix=v1_prefix)
    app.include_router(fairness_routes.router, prefix=v1_prefix)
    app.include_router(qa_routes, prefix=v1_prefix)
    app.include_router(jobs_routes.router, prefix=v1_prefix)

    # RBAC test route
    @app.get(f"{v1_prefix}/admin/ping")
    async def admin_ping(_user=Depends(require_roles(UserRole.ORG_ADMIN))):
        return {"pong": True}

    # Convenience alias: /api/me and /api/v1/me
    from .deps.auth import get_current_user
    from .models.auth import UserOut

    @app.get("/api/me", response_model=UserOut)
    async def api_me(user=Depends(get_current_user)):
        return UserOut.model_validate(user)

    @app.get(f"{v1_prefix}/me", response_model=UserOut)
    async def api_me_v1(user=Depends(get_current_user)):
        return UserOut.model_validate(user)

    @app.get("/")
    async def root():
        return JSONResponse({"ok": True})

    @app.on_event("startup")
    async def on_startup():
        if settings.local_mode:
            await init_local_database()
            from backend.scripts.seed_dev import seed

            await seed()
            # Start background scheduler for daily ingestion
            _start_scheduler(app)
            return
        # Dev convenience: ensure MinIO bucket exists
        s = get_settings()
        try:
            client = Minio(
                endpoint=s.s3_endpoint.replace("http://", "").replace("https://", ""),
                access_key=s.s3_access_key,
                secret_key=s.s3_secret_key,
                secure=s.s3_endpoint.startswith("https://"),
            )
            if s.s3_bucket and not client.bucket_exists(s.s3_bucket):
                client.make_bucket(s.s3_bucket)
                logger.info("created_minio_bucket", bucket=s.s3_bucket)
        except Exception as e:
            logger.warning("minio_init_failed", error=str(e))
        _start_scheduler(app)

    @app.on_event("shutdown")
    async def on_shutdown():
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("scheduler_stopped")

    return app


def _start_scheduler(app: FastAPI) -> None:
    """Start APScheduler for daily data ingestion and weekly model retraining."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("apscheduler_not_installed — scheduled ingestion disabled")
        return

    scheduler = AsyncIOScheduler()

    # Daily ingestion at 6 AM UTC
    scheduler.add_job(
        _daily_ingest,
        "cron",
        hour=6,
        minute=0,
        id="daily_ingest",
        replace_existing=True,
    )

    # Weekly model retraining on Mondays at 7 AM UTC
    scheduler.add_job(
        _weekly_retrain,
        "cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="weekly_retrain",
        replace_existing=True,
    )

    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("scheduler_started", jobs=["daily_ingest@06:00UTC", "weekly_retrain@mon_07:00UTC"])


async def _daily_ingest() -> None:
    """Run all ETL pipelines for the last 7 days of data."""
    from .db.session import AsyncSessionLocal
    from .services.etl.era5 import flow_era5_ingest
    from .services.etl.openaq import flow_openaq_ingest
    from .services.etl.who_gho import flow_who_gho_ingest
    from .services.etl.population import flow_population_vulnerability
    from .services.etl.google_trends import flow_google_trends_ingest

    logger.info("scheduled_daily_ingest_started")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    try:
        async with AsyncSessionLocal() as db:
            result_era5 = await flow_era5_ingest(db, start, now)
            logger.info("daily_ingest_era5", rows=result_era5.get("rows", 0))
    except Exception as e:
        logger.error("daily_ingest_era5_failed", error=str(e))

    try:
        async with AsyncSessionLocal() as db:
            result_aq = await flow_openaq_ingest(db, start, now)
            logger.info("daily_ingest_openaq", rows=result_aq.get("rows", 0))
    except Exception as e:
        logger.error("daily_ingest_openaq_failed", error=str(e))

    try:
        async with AsyncSessionLocal() as db:
            result_gho = await flow_who_gho_ingest(db)
            logger.info("daily_ingest_who_gho", rows=result_gho.get("rows", 0))
    except Exception as e:
        logger.error("daily_ingest_who_gho_failed", error=str(e))

    try:
        async with AsyncSessionLocal() as db:
            result_pop = await flow_population_vulnerability(db)
            logger.info("daily_ingest_population", rows=result_pop.get("rows", 0))
    except Exception as e:
        logger.error("daily_ingest_population_failed", error=str(e))

    try:
        async with AsyncSessionLocal() as db:
            result_gt = await flow_google_trends_ingest(db, lookback_weeks=4)
            logger.info("daily_ingest_google_trends", rows=result_gt.get("rows", 0))
    except Exception as e:
        logger.error("daily_ingest_google_trends_failed", error=str(e))

    logger.info("scheduled_daily_ingest_complete")


async def _weekly_retrain() -> None:
    """Retrain all ML models (placeholder — wired in Task #10)."""
    logger.info("scheduled_weekly_retrain_started")
    try:
        from .services.ml.train import retrain_all_models
        from .db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await retrain_all_models(db)
        logger.info("scheduled_weekly_retrain_complete")
    except ImportError:
        logger.info("ml_train_module_not_ready — skipping retrain")
    except Exception as e:
        logger.error("scheduled_weekly_retrain_failed", error=str(e))


app = create_app()
