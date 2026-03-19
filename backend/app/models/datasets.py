from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import CamelModel


class DatasetOut(CamelModel):
    id: int
    name: str
    source: str | None = None
    license: str | None = None
    spatial: str | None = None
    temporal: str | None = None
    freshness: datetime | None = None
    meta_json: dict[str, Any] | None = None


class DatasetLineage(CamelModel):
    dataset: DatasetOut
    versions: list[dict]
    ingest_runs: list[dict]
