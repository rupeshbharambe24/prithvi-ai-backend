from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class UserRole(str, enum.Enum):
    ORG_ADMIN = "OrgAdmin"
    EPIDEMIOLOGIST = "Epidemiologist"
    HOSPITAL_OPS = "HospitalOps"
    FIELD_OFFICER = "FieldOfficer"
    VIEWER = "Viewer"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            native_enum=False,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    org_id: Mapped[int | None] = mapped_column(ForeignKey("orgs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    org: Mapped["Org"] = relationship(back_populates="users")
