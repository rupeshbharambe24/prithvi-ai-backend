from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import typer

from ..config import get_settings
from ..db.session import AsyncSessionLocal
from ..services.etl.era5 import flow_era5_ingest
from ..services.etl.population import flow_population_vulnerability
from ..services.etl.who_gho import flow_who_gho_ingest
from ..db.models import Region


app = typer.Typer(help="Ingestion and import commands")


@app.command()
def import_regions(file: str):
    """Import regions from a GeoJSON file (simple MultiPolygon + Point center)."""
    import json
    settings = get_settings()

    async def _run():
        async with AsyncSessionLocal() as db:
            data = json.load(open(file, "r", encoding="utf-8"))
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                name = props.get("name") or props.get("NAME") or "Region"
                code = props.get("code") or props.get("CODE")
                r = Region(name=name, code=code)
                if settings.local_mode:
                    geom = feat.get("geometry")
                    coords = geom.get("coordinates", [[[]]])
                    ring = coords[0][0] if geom.get("type") == "MultiPolygon" else coords[0]
                    lons = [pt[0] for pt in ring]
                    lats = [pt[1] for pt in ring]
                    r.bounds_geom = geom
                    r.center = {"lat": sum(lats) / len(lats), "lng": sum(lons) / len(lons)}
                else:
                    from shapely.geometry import shape
                    from geoalchemy2.shape import from_shape

                    geom = shape(feat.get("geometry"))
                    center = geom.centroid
                    r.bounds_geom = from_shape(geom, srid=4326)
                    r.center = from_shape(center, srid=4326)
                db.add(r)
            await db.commit()

    asyncio.run(_run())


@app.command()
def etl_run(dataset: str, start: Optional[str] = None, end: Optional[str] = None):
    async def _run():
        async with AsyncSessionLocal() as db:
            if dataset == "era5":
                s = datetime.fromisoformat(start).replace(tzinfo=timezone.utc) if start else datetime(2024, 7, 1, tzinfo=timezone.utc)
                e = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) if end else datetime(2024, 7, 2, tzinfo=timezone.utc)
                await flow_era5_ingest(db, s, e)
            elif dataset == "who_gho":
                await flow_who_gho_ingest(db)
            elif dataset == "population":
                await flow_population_vulnerability(db)
            else:
                raise typer.BadParameter("Unknown dataset")

    asyncio.run(_run())


@app.command()
def etl_backfill(dataset: str, start: str, end: str):
    return etl_run(dataset, start, end)


if __name__ == "__main__":
    app()
