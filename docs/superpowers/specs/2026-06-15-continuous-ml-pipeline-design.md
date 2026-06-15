# Continuous Train → Predict → Verify → Retrain Pipeline

**Date:** 2026-06-15
**Status:** Approved (design), pending implementation plan
**Scope:** Backend (`backend/backend/app`)

## Problem

The platform ingests real climate/health data daily and retrains models weekly, but the
`forecasts` table is only ever populated once, by `scripts/seed_dev.py`, which self-guards
(`if forecast count > 0: return`). Consequences observed on 2026-06-15:

- `features` fresh to 2026-06-15, `model_versions` retrained 2026-06-15, but `forecasts`
  frozen at max `target_date` 2026-04-04 (seeded 2026-03-31).
- Frontend queries forecasts for *upcoming* dates → empty sets → `Math.max([])` = `-Infinity`,
  blank cards, "Select a region to view data" on Overview/Heat/Disease/Surge/Air pages.

Root cause: **no scheduled step regenerates forward forecasts**, and **no step scores past
forecasts against realized actuals**. The scheduler in `main.py` runs `_daily_ingest` and a
stub `_weekly_retrain` only.

## Goals

1. Forward forecasts always current (regenerated daily).
2. Forecasts scored against realized actuals → live production accuracy signal.
3. Weekly retrain with champion/challenger promotion (no silent degradation).
4. Drift monitoring drives off-cycle retraining.
5. All performance signals logged to existing tables + surfaced on existing console pages.
6. Runnable on the current local Windows + SQLite + single-uvicorn setup, no new infra.

## Cadence Decision

- **Daily:** ingest, score matured forecasts, refresh forward forecasts (horizon 14d), drift check.
- **Weekly (Mon):** retrain all models, champion/challenger promote, backtest + fairness, then
  one daily run so forecasts reflect the new champion.
- **Event-driven:** critical drift (PSI ≥ 0.25) triggers off-cycle retrain for the affected target.

Rationale: weather forecasts update daily (re-run inference daily), but learned relationships
change slowly and only ~1 new labeled row/region/day arrives — daily retraining wastes compute
and makes the model/SHAP drivers jitter. Forecast labels mature only after `horizon` days, so a
weekly retrain aligns with availability of a full week of ground truth. Drift-triggered retrain
provides fast reaction without daily refits.

## Architecture

Both the APScheduler jobs and a new CLI are **thin callers** of one orchestration module —
identical logic, no duplication.

| File | Change |
|---|---|
| `app/services/pipeline/runner.py` | **New.** `run_daily_pipeline(db)`, `run_weekly_pipeline(db)`. |
| `app/services/ml/scoring.py` | **New.** `score_due_forecasts(db)` — pair matured forecasts with actuals → `backtest_scores`. |
| `app/services/ml/registry.py` | Add `active_model(db, target)` (status-aware) and `promote_if_better(db, mv)`. Keep `latest_model()` for back-compat. |
| `app/db/models/model_version.py` | Add `status` column: `active` / `shadow` / `rejected`. |
| `app/db/migrations/versions/0005_*.py` | Alembic migration for the `status` column. |
| `app/main.py` | `_daily_ingest`/`_weekly_retrain` bodies call the pipeline functions. |
| `app/scripts/run_pipeline.py` | **New.** CLI: `python -m backend.app.scripts.run_pipeline daily|weekly|score|forecast`. |

## Data Flow

### `run_daily_pipeline(db)` (06:00 UTC daily; CLI `daily`)
1. **Ingest** — 5 ETL flows (era5/open-meteo, openaq, who_gho, population, google_trends),
   trailing 7 days. (Existing `_daily_ingest` logic.)
2. **Score matured forecasts** — `score_due_forecasts`: for each forecast with
   `target_date < today` not yet scored and whose actual now exists, compute error and write a
   `backtest_scores` row keyed by (target, region, horizon window). Idempotent — never
   double-scores.
3. **Refresh forward forecasts** — per region × target: `DELETE FROM forecasts WHERE
   region_id=? AND type=? AND target_date >= today`, then regenerate `horizon=14` from the
   **active** model (`active_model`) and insert. Delete-then-insert in one transaction per
   region×target.
4. **Drift check** — `compute_all_drift`; PSI ≥ 0.25 flags the target for off-cycle retrain and
   auto-creates a drift alert (existing behavior).

### `run_weekly_pipeline(db)` (Mon 07:00 UTC; CLI `weekly`)
1. **Retrain** all target×region models → registered as new `model_version` with `status='shadow'`.
2. **Champion/challenger** — `promote_if_better`: compare shadow `skill_score` (tie-break RMSE)
   to current `active`. Promote (set `active`, demote previous to `rejected`/inactive) only if
   `>=`; else mark shadow `rejected` and log `challenger_rejected`. Fail-safe: on any comparison
   error, keep existing champion.
3. **Backtest + fairness** on the promoted model (`simple_rolling_backtest`, `evaluate_heat_fairness`).
4. Run `run_daily_pipeline` once so forecasts reflect the new champion.

### Drift-triggered retrain
Daily step 4 critical PSI → invoke the weekly retrain path for the affected target only.

## Schema Change

`model_versions.status TEXT NOT NULL DEFAULT 'active'`. Values: `active` (live, one per
target), `shadow` (newly trained, awaiting promotion), `rejected` (lost champion/challenger).
`active_model()` selects newest `status='active'`; falls back to newest row if none flagged
(back-compat with the 60 pre-existing versions). Created via Alembic `0005` (prod) and
`create_all` (local SQLite).

## Monitoring

- `model_versions.metrics_json` + `status` → training skill log + which model is live (Models page).
- `backtest_scores` → rolling forecast-vs-actual RMSE/MAE/coverage **by horizon**; exposed via the
  existing QA/fairness router for the Models/Fairness page to chart skill-over-time.
- `drift_reports` → PSI/KS per feature (Fairness & QA page).
- structlog lines per step: `pipeline_daily_ingest`, `forecasts_refreshed rows=N`,
  `forecasts_scored n=N`, `challenger_promoted/rejected target=.. old_skill=.. new_skill=..`,
  `drift_triggered_retrain target=..`.

## Error Handling

- Each step in its own try/except with its own DB session; one failing ETL source / region's
  training logs and continues — never aborts the run. Pipeline returns `{step: status|rows}`.
- Champion/challenger never auto-promotes on error (keeps current champion).
- Forecast refresh delete+insert is transactional per region×target — a crash can't leave a
  region with zero future forecasts.
- CLI prints the summary dict and exits non-zero only on total failure.

## Testing (pytest, SQLite fixture)

- `score_due_forecasts`: seeded past forecast + matching actual → correct `backtest_scores` row;
  re-run → no duplicate (idempotent).
- `promote_if_better`: better challenger promotes & demotes old; worse challenger rejected; error
  keeps champion.
- `run_daily_pipeline`: on seeded DB, forecasts with `target_date >= today` exist afterward; no
  duplicate future rows.
- CLI smoke: `run_pipeline daily` returns a summary dict, exits 0.

## Out of Scope (YAGNI)

- Celery/Beat distributed path (in-process APScheduler is sufficient for current setup).
- Auto-rollback on live error spike (champion/challenger gate covers degradation).
- Hyperparameter search / model architecture changes.
