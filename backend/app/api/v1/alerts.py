from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...deps.auth import require_roles
from ...deps import csrf_protect
from ...db.models.user import UserRole
from ...db.session import get_db
from ...config import get_settings
from ...services.alerts.engine import evaluate_rules


router = APIRouter(prefix="/alerts", tags=["alerts"])


def _json_value(value: Any, fallback: Any):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return fallback
    return value


@router.get("/rules")
async def list_rules(_=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    res = await db.execute(text("SELECT id, name, metric, condition, threshold, horizon_days, severity, channels FROM alert_rules ORDER BY id"))
    rows = res.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "metric": r[2],
            "condition": r[3],
            "threshold": r[4],
            "horizonDays": r[5],
            "severity": r[6],
            "channels": _json_value(r[7], []),
        }
        for r in rows
    ]


@router.post("/rules", dependencies=[Depends(csrf_protect)])
async def create_rule(payload: dict, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    params = {
        "name": payload.get("name", "rule"),
        "metric": payload.get("metric", "heat"),
        "region_filter": payload.get("regionFilter", "*"),
        "condition": payload.get("condition", ">="),
        "threshold": payload.get("threshold", 0.7),
        "horizon": int(payload.get("horizonDays", 3)),
        "severity": payload.get("severity", "warn"),
        "channels": json.dumps(payload.get("channels", ["email"])),
        "cooldown": int(payload.get("cooldownMinutes", 60)),
        "meta_json": json.dumps({}),
    }
    if settings.local_mode:
        cur = await db.execute(
            text(
                """
                INSERT INTO alert_rules (org_id, name, metric, region_filter, condition, threshold, horizon_days, severity, channels, cooldown_minutes, active, created_by, meta_json)
                VALUES (NULL,:name,:metric,:region_filter,:condition,:threshold,:horizon,:severity,:channels,:cooldown,1,NULL,:meta_json)
                RETURNING id
                """
            ),
            params,
        )
    else:
        cur = await db.execute(
            text(
                """
                INSERT INTO alert_rules (org_id, name, metric, region_filter, condition, threshold, horizon_days, severity, channels, cooldown_minutes, active, created_by, meta_json)
                VALUES (NULL,:name,:metric,:region_filter,:condition,:threshold,:horizon,:severity,:channels,:cooldown,true,NULL,'{}'::jsonb)
                RETURNING id
                """
            ),
            params,
        )
    rid = cur.scalar()
    await db.commit()
    return {"id": rid}


@router.post("/run", dependencies=[Depends(csrf_protect)])
async def run_alerts(_=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    res = await evaluate_rules(db)
    return res


@router.get("")
async def list_alerts(status: str | None = None, regionId: int | None = None, severity: str | None = None, _=Depends(require_roles(UserRole.VIEWER)), db: AsyncSession = Depends(get_db)):
    sql = "SELECT id, rule_id, region_id, severity, started_at, ended_at, status, payload_json FROM alerts WHERE 1=1"
    params: dict[str, Any] = {}
    if status:
        sql += " AND status=:status"
        params["status"] = status
    if regionId:
        sql += " AND region_id=:regionId"
        params["regionId"] = regionId
    if severity:
        sql += " AND severity=:severity"
        params["severity"] = severity
    sql += " ORDER BY started_at DESC"
    rows = (await db.execute(text(sql), params)).fetchall()
    out = []
    for r in rows:
        started = r[4].isoformat() if hasattr(r[4], 'isoformat') else str(r[4])
        ended = r[5].isoformat() if r[5] and hasattr(r[5], 'isoformat') else (str(r[5]) if r[5] else None)
        out.append({
            "id": r[0],
            "ruleId": r[1],
            "regionId": r[2],
            "severity": r[3],
            "startedAt": started,
            "endedAt": ended,
            "status": r[6],
            "payload": _json_value(r[7], {}),
        })
    return out


@router.patch("/{alert_id}", dependencies=[Depends(csrf_protect)])
async def update_alert(alert_id: int, payload: dict, _=Depends(require_roles(UserRole.ORG_ADMIN, UserRole.EPIDEMIOLOGIST)), db: AsyncSession = Depends(get_db)):
    new_status = payload.get("status")
    if new_status not in {"ack", "resolved"}:
        raise HTTPException(status_code=400, detail="invalid status")
    now = datetime.now(timezone.utc)
    ended = now if new_status == "resolved" else None
    await db.execute(text("UPDATE alerts SET status=:st, updated_at=:now, ended_at=COALESCE(ended_at,:ended) WHERE id=:id"), {"st": new_status, "now": now, "ended": ended, "id": alert_id})
    await db.commit()
    settings = get_settings()
    if not settings.local_mode:
        import json
        import redis

        r = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        r.publish("alerts", json.dumps({"event": "alert-updated", "id": alert_id, "status": new_status}))
    return {"ok": True}
