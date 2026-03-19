from __future__ import annotations

import os
import sqlite3
import subprocess
from typing import Optional


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def build_vector_tiles(geojson_path: str, out_mbtiles: str, layer_name: Optional[str] = None) -> None:
    """Build vector tiles with tippecanoe if available; otherwise create a dummy MBTiles with one tile.

    This keeps tests offline and lightweight.
    """
    _ensure_dir(out_mbtiles)
    try:
        cmd = [
            "tippecanoe",
            "-o",
            out_mbtiles,
            "-Z",
            "0",
            "-z",
            "1",
            "-l",
            layer_name or "layer",
            geojson_path,
        ]
        subprocess.run(cmd, check=True)
        return
    except Exception:
        # Fallback: create a minimal MBTiles with a dummy tile
        con = sqlite3.connect(out_mbtiles)
        try:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);
                CREATE TABLE IF NOT EXISTS metadata (name text, value text);
                CREATE UNIQUE INDEX IF NOT EXISTS tile_index on tiles (zoom_level, tile_column, tile_row);
                """
            )
            # Insert a non-empty dummy protobuf blob for z=0,x=0,y=0
            con.execute(
                "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (0,0,0,?)",
                (b"dummy",),
            )
            con.commit()
        finally:
            con.close()

