from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict
import json

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def send_stub_deliveries(db: AsyncSession, alert_id: int, channels: List[str], payload: Dict) -> None:
    for ch in channels:
        meta = json.dumps(payload)
        sql = """
            INSERT INTO deliveries (alert_id, channel, address, status, provider_message_id, attempts, last_error, meta_json, created_at)
            VALUES (:alert_id, :channel, '', 'sent', 'stub', 1, NULL, :meta, :ts)
        """
        await db.execute(
            text(sql),
            {
                "alert_id": alert_id,
                "channel": ch,
                "meta": meta,
                "ts": datetime.now(timezone.utc),
            },
        )
    await db.commit()
