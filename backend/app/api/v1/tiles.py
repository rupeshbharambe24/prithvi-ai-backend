from __future__ import annotations

import os
import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...config import get_settings


router = APIRouter(tags=["tiles"])


def _tiles_path() -> str:
    s = get_settings()
    return os.getenv("TILES_PATH", "/tmp/tiles")


@router.get("/tiles/{layer}/{z}/{x}/{y}.mvt")
async def get_tile(layer: str, z: int, x: int, y: int, _user=Depends(require_roles(UserRole.VIEWER))):
    path = os.path.join(_tiles_path(), f"{layer}.mbtiles")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Layer not found")
    # XYZ to TMS tile_row
    tms_y = (1 << z) - 1 - y
    con = sqlite3.connect(path)
    try:
        cur = con.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, tms_y),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tile not found")
        data = row[0]
        return Response(content=data, media_type="application/x-protobuf")
    finally:
        con.close()

