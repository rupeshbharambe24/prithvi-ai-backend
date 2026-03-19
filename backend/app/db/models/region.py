from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base
from ..types import geometry_column


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    bounds_geom: Mapped[object | None] = mapped_column(geometry_column("MULTIPOLYGON"), nullable=True)
    center: Mapped[object | None] = mapped_column(geometry_column("POINT"), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    parent: Mapped["Region"] = relationship(remote_side=[id])
