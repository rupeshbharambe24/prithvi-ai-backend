from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...db.models.user import UserRole
from ...db.session import get_db


router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/audit")
async def audit(from_: str | None = None, to: str | None = None, userId: int | None = None, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    # Stub: build redacted rows from recent alerts as audit-like entries
    rows = (await db.execute(text("SELECT id, created_at, status FROM alerts ORDER BY created_at DESC LIMIT 10"))).fetchall()
    items = [
        {"when": r[1].isoformat(), "userId": userId or 0, "action": "alert", "path": "/redacted", "status": r[2], "redacted": True}
        for r in rows
    ]
    if not items:
        items = [{"when": datetime.now(timezone.utc).isoformat(), "userId": userId or 0, "action": "none", "path": "/redacted", "status": "none", "redacted": True}]
    return {"items": items}
