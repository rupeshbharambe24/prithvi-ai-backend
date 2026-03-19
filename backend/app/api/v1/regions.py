from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import Region
from ...db.session import get_db
from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...models.regions import RegionOut


router = APIRouter(prefix="/regions", tags=["regions"])


def _region_center(region: Region) -> dict | None:
    if isinstance(region.center, dict):
        return region.center
    if region.center is None:
        return None
    from shapely.geometry import mapping
    from geoalchemy2.shape import to_shape

    center_geo = mapping(to_shape(region.center))
    if center_geo.get("type") != "Point":
        return None
    lon, lat = center_geo.get("coordinates")
    return {"lat": lat, "lng": lon}


def _region_bbox(region: Region) -> list | None:
    if isinstance(region.bounds_geom, dict):
        geom = region.bounds_geom
        coords = geom.get("coordinates", [])
        flat: list[list[float]] = []
        if geom.get("type") == "MultiPolygon":
            for polygon in coords:
                for ring in polygon:
                    flat.extend(ring)
        elif geom.get("type") == "Polygon":
            for ring in coords:
                flat.extend(ring)
        if not flat:
            return None
        lons = [pt[0] for pt in flat]
        lats = [pt[1] for pt in flat]
        return [[min(lons), min(lats)], [max(lons), max(lats)]]
    if region.bounds_geom is None:
        return None
    from shapely.geometry import mapping
    from geoalchemy2.shape import to_shape

    bounds_geo = mapping(to_shape(region.bounds_geom))
    if bounds_geo.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    coords = []

    def collect(raw):
        if raw and isinstance(raw[0][0], (float, int)):
            return raw
        out = []
        for poly in raw:
            out.extend(poly)
        return out

    try:
        all_coords = collect(bounds_geo.get("coordinates"))
        flat = [pt for ring in all_coords for pt in ring]
        lons = [p[0] for p in flat]
        lats = [p[1] for p in flat]
        return [[min(lons), min(lats)], [max(lons), max(lats)]]
    except Exception:
        return None


@router.get("/", response_model=list[RegionOut])
async def list_regions(
    _user=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db), bbox: str | None = Query(default=None)
):
    # BBox filtering could be applied with PostGIS, but noop for now
    res = await db.execute(select(Region))
    regions = list(res.scalars())
    out: list[RegionOut] = []
    for r in regions:
        out.append(
            RegionOut(
                id=r.id,
                code=r.code,
                name=r.name,
                center=_region_center(r),
                bounds=_region_bbox(r),
                parent_id=r.parent_id,
            )
        )
    return out


# Alias without trailing slash
@router.get("", response_model=list[RegionOut], include_in_schema=False)
async def list_regions_noslash(
    _user=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)
):
    return await list_regions(_user, db)
