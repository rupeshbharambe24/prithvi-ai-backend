from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ...config import get_settings
from .providers import send_stub_deliveries


def _map_metric_to_forecast_type(metric: str) -> str:
    # Accept namespaced metrics from FE and map to forecasts.type
    mapping = {
        "risk.heat": "heat",
        "hospital.ed": "surge",
        "air.pm25": "pm25",
        "disease.dengue": "disease",
        "heat": "heat",
        "surge": "surge",
        "pm25": "pm25",
        "disease": "disease",
    }
    return mapping.get(metric, metric)


async def evaluate_rules(db: AsyncSession) -> Dict:
    # Fetch active rules
    rows = (await db.execute(text("SELECT id, metric, region_filter, condition, threshold, horizon_days, severity, channels, cooldown_minutes FROM alert_rules WHERE active=true"))).fetchall()
    created = 0
    evaluated = 0
    settings = get_settings()
    redis_client = None
    if not settings.local_mode:
        import redis

        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    for rid, metric, region_filter, cond, threshold, horizon_days, severity, channels, cooldown in rows:
        evaluated += 1
        if isinstance(channels, str):
            try:
                channels = json.loads(channels)
            except Exception:
                channels = ["email"]
        # Regions scope
        region_ids = None
        if region_filter and region_filter != "*":
            try:
                region_ids = [int(x) for x in str(region_filter).split(",") if x]
            except Exception:
                region_ids = None
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=int(horizon_days))
        # Query forecasts meeting condition
        base_sql = """
            SELECT region_id, target_date, value, p05, p95 FROM forecasts
            WHERE type=:metric AND target_date BETWEEN :start AND :end
        """
        ftype = _map_metric_to_forecast_type(metric)
        params = {"metric": ftype, "start": start, "end": end}
        if region_ids and not settings.local_mode:
            base_sql += " AND region_id = ANY(:region_ids)"
            params["region_ids"] = region_ids
        res = await db.execute(text(base_sql), params)
        for region_id, target_date, value, p05, p95 in res.fetchall():
            if region_ids and settings.local_mode and region_id not in region_ids:
                continue
            if not _meets(value, cond, threshold):
                continue
            # cooldown check: any open alert in last cooldown minutes?
            cool_ts = datetime.now(timezone.utc) - timedelta(minutes=int(cooldown or 60))
            existing = await db.execute(text("SELECT id FROM alerts WHERE rule_id=:rule AND region_id=:region AND status='open' AND started_at>=:cool"), {"rule": rid, "region": region_id, "cool": cool_ts})
            if existing.scalar() is not None:
                continue
            # Create alert
            td_str = target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date)[:10]
            payload = {"metric": metric, "value": value, "threshold": threshold, "targetDate": td_str}
            now = datetime.now(timezone.utc)
            if settings.local_mode:
                cur = await db.execute(
                    text(
                        """
                        INSERT INTO alerts (rule_id, region_id, severity, started_at, ended_at, status, payload_json, created_at, updated_at)
                        VALUES (:rule_id,:region_id,:severity,:started_at,NULL,'open',:payload,:created_at,:updated_at)
                        RETURNING id
                        """
                    ),
                    {
                        "rule_id": rid,
                        "region_id": region_id,
                        "severity": severity,
                        "started_at": now,
                        "payload": json.dumps(payload),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                cur = await db.execute(
                    text(
                        """
                        INSERT INTO alerts (rule_id, region_id, severity, started_at, ended_at, status, payload_json, created_at, updated_at)
                        VALUES (:rule_id,:region_id,:severity,:started_at,NULL,'open',cast(:payload as jsonb),:created_at,:updated_at)
                        RETURNING id
                        """
                    ),
                    {
                        "rule_id": rid,
                        "region_id": region_id,
                        "severity": severity,
                        "started_at": now,
                        "payload": json.dumps(payload),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            alert_id = cur.scalar()
            await db.commit()
            created += 1
            # Deliveries stubs
            await send_stub_deliveries(db, alert_id, channels or ["email"], payload)
            # SSE event
            if redis_client is not None:
                redis_client.publish("alerts", json.dumps({"event": "alert-created", "id": alert_id, "ruleId": rid, "regionId": region_id, "severity": severity}))
    return {"evaluated": evaluated, "created": created}


def _meets(value: float, cond: str, threshold: float) -> bool:
    if cond == ">":
        return value > threshold
    if cond == ">=":
        return value >= threshold
    if cond == "<":
        return value < threshold
    if cond == "<=":
        return value <= threshold
    return False
