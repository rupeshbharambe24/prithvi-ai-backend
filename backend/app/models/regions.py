from __future__ import annotations

from typing import Any
from pydantic import Field

from .base import CamelModel


class RegionOut(CamelModel):
    id: int
    code: str | None = None
    name: str
    center: dict | None = Field(default=None, description="{lat,lng}")
    bounds: list | None = Field(default=None, description="[[minLng,minLat],[maxLng,maxLat]]")
    parent_id: int | None = Field(default=None, alias="parentId")
