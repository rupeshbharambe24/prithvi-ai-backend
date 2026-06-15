"""On-demand pipeline runner. Same logic as the scheduler.

Usage:
  python -m backend.app.scripts.run_pipeline daily      # ingest+score+forecast+drift
  python -m backend.app.scripts.run_pipeline daily --no-ingest
  python -m backend.app.scripts.run_pipeline weekly      # retrain+promote+fairness+refresh
  python -m backend.app.scripts.run_pipeline score       # score matured forecasts only
  python -m backend.app.scripts.run_pipeline forecast    # refresh forward forecasts only
"""
from __future__ import annotations

import asyncio
import sys
from typing import Dict

from ..db.session import AsyncSessionLocal
from ..services.pipeline.runner import (
    run_daily_pipeline, run_weekly_pipeline, refresh_forecasts,
)
from ..services.ml.scoring import score_due_forecasts


async def run(mode: str, do_ingest: bool = True) -> Dict:
    async with AsyncSessionLocal() as db:
        if mode == "daily":
            return await run_daily_pipeline(db, do_ingest=do_ingest)
        if mode == "weekly":
            return await run_weekly_pipeline(db)
        if mode == "score":
            return await score_due_forecasts(db)
        if mode == "forecast":
            return await refresh_forecasts(db)
        raise SystemExit(f"unknown mode: {mode} (use daily|weekly|score|forecast)")


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "daily"
    do_ingest = "--no-ingest" not in args
    result = asyncio.run(run(mode, do_ingest=do_ingest))
    print(result)


if __name__ == "__main__":
    main()
