from __future__ import annotations

from datetime import datetime, timezone

# Optional Prefect registration point; falls back to simple function calls
try:
    from prefect import flow
except Exception:  # pragma: no cover
    def flow(fn):
        return fn

from .era5 import flow_era5_ingest
from .population import flow_population_vulnerability
from .who_gho import flow_who_gho_ingest


@flow(name="era5_ingest")
def era5_ingest_flow(start: datetime, end: datetime):
    return flow_era5_ingest  # type: ignore[return-value]


@flow(name="population_vulnerability")
def population_vulnerability_flow():
    return flow_population_vulnerability  # type: ignore[return-value]


@flow(name="who_gho_ingest")
def who_gho_ingest_flow():
    return flow_who_gho_ingest  # type: ignore[return-value]

