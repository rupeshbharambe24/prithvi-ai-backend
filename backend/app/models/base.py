from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class CamelModel(BaseModel):
    class Config:
        populate_by_name = True
        alias_generator = to_camel

