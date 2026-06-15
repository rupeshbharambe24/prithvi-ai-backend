from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..types import json_type


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(50), index=True)
    algo: Mapped[str] = mapped_column(String(50))
    params_json = mapped_column(json_type(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    path: Mapped[str] = mapped_column(String(255))
    metrics_json = mapped_column(json_type(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="active", index=True
    )
