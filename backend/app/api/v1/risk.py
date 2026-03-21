from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db
from ...db.models import Region

router = APIRouter(prefix="/risk", tags=["risk"])


def _parse_date(val) -> str:
    """Parse a date value from SQLite (string) or Postgres (datetime) to ISO date string."""
    if isinstance(val, str):
        return val[:10]  # '2026-03-19 08:...' -> '2026-03-19'
    return val.date().isoformat() if hasattr(val, 'date') else str(val)[:10]


def _parse_json(val):
    """Parse JSON that may be a string (SQLite) or already parsed (Postgres)."""
    if val is None:
        return None
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return None
    return val


@router.get("/heat")
async def heat_risk(regionId: int, horizon: str = "7d", _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    days = int(horizon.strip("d")) if horizon.endswith("d") else 7
    region = await db.get(Region, regionId)
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=days + 1)
    res = await db.execute(text("""
        SELECT target_date, value, p05, p95, drivers_json FROM forecasts
        WHERE region_id=:rid AND type='heat' AND target_date >= :start AND target_date <= :end
        ORDER BY target_date ASC
    """), {"rid": regionId, "start": start, "end": end})
    rows = res.fetchall()
    series = []
    drivers = []
    for r in rows:
        series.append({"date": _parse_date(r[0]), "risk": r[1], "p05": r[2], "p95": r[3]})
        if r[4] and not drivers:
            drivers = _parse_json(r[4]) or []
    if not series:
        return {"series": [], "drivers": [], "status": "no_data",
                "message": "No heat forecast data. Run ETL + model training first."}
    return {"series": series, "drivers": drivers, "map": {}}


@router.get("/disease")
async def disease_risk(type: str = "dengue", regionId: int = 1, horizon: str = "28d", _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    days = int(horizon.strip("d")) if horizon.endswith("d") else 28
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=days + 1)
    res = await db.execute(text("""
        SELECT target_date, value, p05, p95, drivers_json FROM forecasts
        WHERE region_id=:rid AND type='disease' AND target_date >= :start AND target_date <= :end
        ORDER BY target_date ASC
    """), {"rid": regionId, "start": start, "end": end})
    rows = res.fetchall()
    series = [{"date": _parse_date(r[0]), "risk": r[1], "p05": r[2], "p95": r[3]} for r in rows]
    drivers = []
    for r in rows:
        if len(r) > 4 and r[4] and not drivers:
            drivers = _parse_json(r[4]) or []
            break
    if not series:
        return {"series": [], "drivers": [], "status": "no_data",
                "message": "No disease forecast data. Run ETL + model training first."}
    return {"series": series, "drivers": drivers}
