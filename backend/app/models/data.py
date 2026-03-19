from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import CamelModel


class SeriesPoint(CamelModel):
    ts: datetime
    value: float
    unit: str | None = None


class SeriesMeta(CamelModel):
    feature_key: str
    region_id: int
    p05: float | None = None
    p95: float | None = None


class SeriesResponse(CamelModel):
    points: list[SeriesPoint]
    meta: SeriesMeta


class QualityResponse(CamelModel):
    last_run: dict | None = None
    issues: dict
