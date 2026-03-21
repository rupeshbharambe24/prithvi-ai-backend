from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db


router = APIRouter(prefix="/air", tags=["air"])


def _parse_date(val) -> str:
    if isinstance(val, str):
        return val[:10]
    return val.date().isoformat() if hasattr(val, 'date') else str(val)[:10]


@router.get("/pm25")
async def pm25(regionId: int, horizon: str = "72h", _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    days = 3
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=days)
    res = await db.execute(text("""
        SELECT target_date, value, p05, p95 FROM forecasts
        WHERE region_id=:rid AND type='pm25' AND target_date >= :start AND target_date <= :end
        ORDER BY target_date ASC
    """), {"rid": regionId, "start": start, "end": end})
    series = [{"date": _parse_date(d), "pm25": v, "p05": p05, "p95": p95} for d, v, p05, p95 in res.fetchall()]
    if not series:
        return {"series": [], "status": "no_data",
                "message": "No PM2.5 forecast data. Run ETL + model training first."}
    return {"series": series}
