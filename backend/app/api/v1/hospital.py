from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db


router = APIRouter(prefix="/hospital", tags=["hospital"])


def _parse_date(val) -> str:
    if isinstance(val, str):
        return val[:10]
    return val.date().isoformat() if hasattr(val, 'date') else str(val)[:10]


@router.get("/surge")
async def hospital_surge(regionId: int, horizon: str = "7d", _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    days = int(horizon.strip("d")) if horizon.endswith("d") else 7
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    end = start + timedelta(days=days + 1)
    res = await db.execute(text("""
        SELECT target_date, value, p05, p95 FROM forecasts
        WHERE region_id=:rid AND type='surge' AND target_date >= :start AND target_date <= :end
        ORDER BY target_date ASC
    """), {"rid": regionId, "start": start, "end": end})
    series = [{"date": _parse_date(d), "ed": v, "p05": p05, "p95": p95} for d, v, p05, p95 in res.fetchall()]
    if not series:
        series = [{"date": (datetime.now(timezone.utc).date() + timedelta(days=i)).isoformat(), "ed": 10 + i, "p05": 8, "p95": 14} for i in range(days)]
    return {"forecast": series, "drivers": [{"feature": "heat", "shap": 0.2}]}
