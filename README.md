PRITHVI-AI Backend

FastAPI backend with a local single-process dev mode and optional Docker infra for advanced setups.

Local quick start

- Prereqs: Python 3.11+
- Setup:

  - cp .env.example .env
  - python -m venv .venv
  - .venv\Scripts\activate
  - pip install -e .
  - uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

- Local mode defaults:

  - SQLite database at `./prithvi.db`
  - in-memory cache/rate-limit/jobs
  - no Redis, MinIO, or Celery required to boot
  - default seeded users are created on startup

- Demo users:

  - `admin@example.com` / `Admin123!`
  - `viewer@example.com` / `Viewer123!`

Optional Docker mode

- Docker files and compose config are still present in `infra/` for containerized setups.

Frontend integration (Vite)

- In `frontend/.env.development.local` set:

  VITE_API_BASE_URL=http://localhost:8000
  VITE_API_PREFIX=/api/v1

- Ensure fetch/Axios includes credentials:

  fetch(url, { credentials: 'include' })

- For POST/PATCH/DELETE, send `X-CSRF-Token` header using the `csrf_token` cookie value.

- During Step 1 wire these pages:

  - Login: POST /api/v1/auth/login, /api/v1/auth/refresh, /api/v1/auth/logout, /api/v1/auth/me
  - Catalog: GET /api/v1/datasets, /api/v1/datasets/{id}/lineage
  - Regions: GET /api/v1/regions
  - SSE heartbeat: GET /api/v1/events/stream

cURL examples

- Login:

  curl -i -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"admin@example.com","password":"Admin123!"}'

- Health:

  curl http://localhost:8000/api/v1/health

- Long job + SSE:

  curl -X POST http://localhost:8000/api/v1/demo/long-job
  curl -N http://localhost:8000/api/v1/events/stream

Features

- FastAPI with versioned routes under /api
- Auth: email+password, JWT in httpOnly cookies, refresh token, CSRF protection
- RBAC roles: OrgAdmin, Epidemiologist, HospitalOps, FieldOfficer, Viewer
- DB: PostgreSQL (TimescaleDB + PostGIS), SQLAlchemy 2.x (async), Alembic migrations
- Cache/Queue: Redis 7, Celery workers + scheduler
- Object store: MinIO wiring (S3-compatible), dev bucket auto-create
- Streaming: SSE endpoint for job progress events
- Observability: structlog, health, Sentry, OpenTelemetry (OTLP)
- Security: CORS allowlist, rate limiting, CSP headers, audit logging
- Tooling: Docker Compose, Makefile, Poetry, pre-commit, mypy, pytest

Acceptance

- OpenAPI at /docs and /openapi.json
- Tests: make test

SSE Example Output

- Logs will show SSE events with job-progress updates during long job execution.

Step 2 additions

- Regions: import GeoJSON to PostGIS (bounds_geom, center, parent_id)
- Datasets/catalog: datasets, dataset_versions, ingest_runs with lineage
- Timeseries: observations (hypertable), features (hypertable) with derived metrics (heat_index, wet_bulb, wbgt)
- Data Quality: dq_issues with API counts
- Tiles: vector tiles (.mbtiles) built from regions/features; served via /tiles
- ETL stubs: flows for era5, who_gho, population using local fixtures
- Caching: Redis cache for hot series queries (5 min TTL)

Step 2 developer UX

- Import pilot regions:

  make import-regions file=backend/backend/tests/fixtures/regions_sample.geojson

- Run ETL on fixtures:

  make etl-run dataset=era5 start=2024-07-01 end=2024-07-03
  make etl-run dataset=who_gho
  make etl-run dataset=population

- Build/push tiles:

  make tiles-build feature=heat_index date=2024-07-01
  make tiles-push feature=heat_index date=2024-07-01

New endpoints

- GET /api/v1/regions
- GET /api/v1/datasets
- GET /api/v1/datasets/{id}/lineage
- GET /api/v1/data/series?regionId=&key=heat_index&from=&to=
- GET /api/v1/data/export?datasetId=&regionId=&from=&to=&fmt=csv
- GET /tiles/{layer}/{z}/{x}/{y}.mvt
- GET /api/v1/data/quality?datasetId=

Step 3 (Modeling & Analytics)

- Train on fixtures:

  make ml-train target=heat

- Forecast all targets (defaults to 7 days):

  make ml-forecast horizon=7

- Backtest:

  make ml-backtest target=heat start=2024-07-01 end=2024-08-01 step=7

- APIs:

  curl "http://localhost:8000/api/v1/risk/heat?regionId=1&horizon=7d"
  curl "http://localhost:8000/api/v1/hospital/surge?regionId=1&horizon=7d"
  curl "http://localhost:8000/api/v1/air/pm25?regionId=1&horizon=72h"
  curl "http://localhost:8000/api/v1/models/registry?target=heat"

Step 4 (KG, Alerts, Scenarios, Optimizer, Fairness)

- KG import and embed:

  make kg-import
  make kg-embed
  curl "http://localhost:8000/api/v1/kg/search?q=heat"

- Alerts:

  curl -X POST http://localhost:8000/api/v1/alerts/rules -H 'Content-Type: application/json' -d '{"name":"Heat >= 0.7","metric":"heat","condition":">=","threshold":0.7,"horizonDays":3,"severity":"warn","channels":["email"]}'
  make alerts-run

- Scenario & Optimizer:

  make scenario-run file=backend/backend/tests/fixtures/scenario_input.json
  make optimizer-run file=backend/backend/tests/fixtures/optimizer_inputs.json

- Fairness & Drift:

  make fairness-eval target=heat
  make drift-check feature=heat_index
