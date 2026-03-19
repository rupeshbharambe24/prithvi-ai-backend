from __future__ import annotations

import os

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


def _local_mode() -> bool:
    raw_local = os.getenv("LOCAL_MODE")
    if raw_local is not None:
        return raw_local.lower() == "true"
    return True


def json_type():
    return JSON().with_variant(JSONB, "postgresql")


def string_list_type():
    return JSON().with_variant(ARRAY(String()), "postgresql")


def geometry_or_json() -> object:
    if _local_mode():
        return json_type()
    from geoalchemy2 import Geometry

    return Geometry


def geometry_column(geometry_type: str) -> object:
    if _local_mode():
        return json_type()
    from geoalchemy2 import Geometry

    return Geometry(geometry_type=geometry_type, srid=4326)
