from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class DQIssue(Base):
    __tablename__ = "dq_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"), index=True)
    check: Mapped[str] = mapped_column(String(100))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str] = mapped_column(String(20))
    details_json = mapped_column(json_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
