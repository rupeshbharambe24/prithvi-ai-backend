from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))
    data_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metrics_json = mapped_column(json_type(), nullable=True)
