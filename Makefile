SHELL := /bin/bash

COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down logs dev migrate seed test lint fmt precommit install

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f api worker scheduler postgres redis minio

dev:
	$(COMPOSE) exec api bash -lc "uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload"

migrate:
	$(COMPOSE) exec api bash -lc "alembic -c backend/alembic.ini upgrade head"

seed:
	$(COMPOSE) exec api bash -lc "python -m backend.scripts.seed_dev"

worker:
	$(COMPOSE) exec worker bash -lc "celery -A backend.app.workers.celery_app:celery_app worker -l info"

test:
	$(COMPOSE) exec -T api bash -lc "pytest -q"

lint:
	$(COMPOSE) exec -T api bash -lc "ruff check backend && black --check backend && isort --check-only backend && mypy backend"

fmt:
	$(COMPOSE) exec -T api bash -lc "ruff check --fix backend || true; black backend; isort backend"

precommit:
	pre-commit install

# Step 2: ETL and tiles
.PHONY: import-regions etl-run etl-backfill tiles-build tiles-push

import-regions:
	$(COMPOSE) exec -T api bash -lc "python -m backend.app.cli.ingest import-regions --file=$$file"

etl-run:
	$(COMPOSE) exec -T api bash -lc "python -m backend.app.cli.ingest etl-run --dataset=$$dataset --start=$$start --end=$$end"

etl-backfill:
	$(COMPOSE) exec -T api bash -lc "python -m backend.app.cli.ingest etl-backfill --dataset=$$dataset --start=$$start --end=$$end"

tiles-build:
	$(COMPOSE) exec -T api bash -lc "python -c 'from backend.app.services.tiles.vector import build_vector_tiles; import os; os.makedirs("/tiles", exist_ok=True); build_vector_tiles("backend/backend/tests/fixtures/regions_sample.geojson", f"/tiles/feature_key=$${feature}:date=$${date}.mbtiles", layer_name="layer")'"

tiles-push:
	@echo "Tiles push to S3 would happen here (dev uses local volume)"

# Step 3: ML
.PHONY: ml-train ml-forecast ml-backtest

ml-train:
	$(COMPOSE) exec -T api bash -lc "python -c 'from backend.app.workers.tasks_models import train_models; print(train_models(\"heat\")); print(train_models(\"surge\"))'"

ml-forecast:
	$(COMPOSE) exec -T api bash -lc "python -c 'from backend.app.workers.tasks_models import run_daily_forecasts; print(run_daily_forecasts(horizon_days=int(\"${horizon:-7}\"), target=\"all\"))'"

ml-backtest:
	$(COMPOSE) exec -T api bash -lc "python -c 'from backend.app.workers.tasks_models import run_backtests; print(run_backtests(target=\"${target}\", start=\"${start}\", end=\"${end}\", step_days=int(\"${step:-7}\")))'"

# Step 4: KG, alerts, scenarios, optimizer, QA
.PHONY: kg-import kg-embed alerts-run scenario-run optimizer-run fairness-eval drift-check

kg-import:
	$(COMPOSE) exec -T api bash -lc "python -c 'import asyncio; from backend.app.db.session import AsyncSessionLocal; from backend.app.services.kg.importer import import_fixtures; async def main():\n\tasync with AsyncSessionLocal() as db: await import_fixtures(db, \"backend/backend/tests/fixtures\"); print(\"ok\")\nasyncio.run(main())'"

kg-embed:
	$(COMPOSE) exec -T api bash -lc "python -c 'import asyncio; from backend.app.db.session import AsyncSessionLocal; from backend.app.services.kg.embed import embed_all_nodes; async def main():\n\tasync with AsyncSessionLocal() as db: print(await embed_all_nodes(db))\nasyncio.run(main())'"

alerts-run:
	$(COMPOSE) exec -T api bash -lc "python -c 'from backend.app.workers.tasks_ops import alerts_run; print(alerts_run())'"

scenario-run:
	$(COMPOSE) exec -T api bash -lc "python - <<'PY'\nimport json\nfrom backend.app.workers.tasks_ops import scenario_run\nprint(scenario_run(json.load(open(\"${file}\", \"r\"))))\nPY"

optimizer-run:
	$(COMPOSE) exec -T api bash -lc "python - <<'PY'\nimport json\nfrom backend.app.workers.tasks_ops import optimizer_run\nprint(optimizer_run(json.load(open(\"${file}\", \"r\"))))\nPY"

fairness-eval:
	$(COMPOSE) exec -T api bash -lc "python - <<'PY'\nimport asyncio\nfrom backend.app.db.session import AsyncSessionLocal\nfrom backend.app.services.qa.fairness import evaluate_heat_fairness\nasync def main():\n\tasync with AsyncSessionLocal() as db:\n\t\tprint(await evaluate_heat_fairness(db))\nasyncio.run(main())\nPY"

drift-check:
	$(COMPOSE) exec -T api bash -lc "python - <<'PY'\nimport asyncio\nfrom backend.app.db.session import AsyncSessionLocal\nfrom backend.app.services.qa.drift import compute_drift\nasync def main():\n\tasync with AsyncSessionLocal() as db:\n\t\tprint(await compute_drift(db, \"${feature}\"))\nasyncio.run(main())\nPY"
