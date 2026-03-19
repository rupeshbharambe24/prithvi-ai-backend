"""initial schema with extensions

Revision ID: 0001_initial
Revises: 
Create Date: 2025-01-01 00:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # Added for postgresql.ENUM

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable extensions (idempotent)
    op.execute("""
    DO $$
    BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
        CREATE EXTENSION IF NOT EXISTS timescaledb;
    END IF;
    END $$;
    """)

    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # Quick, robust fix (make the enum creation idempotent)
    # Before the first op.create_table(...) that uses the role enum, insert this guarded block:
    op.execute("""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
    CREATE TYPE user_role AS ENUM ('OrgAdmin','Epidemiologist','HospitalOps','FieldOfficer','Viewer');
  END IF;
END $$;
""")

    # NOTE: The original `user_role = sa.Enum(...)` block is removed as the type is
    # now created via raw SQL above, and the column definition is updated below.

    # Orgs
    op.create_table(
        "orgs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
    )

    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        # Role column updated to use postgresql.ENUM with create_type=False
        sa.Column(
            'role',
            postgresql.ENUM(
                'OrgAdmin','Epidemiologist','HospitalOps','FieldOfficer','Viewer',
                name='user_role',
                create_type=False # <-- important
            ),
            nullable=False
        ),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("orgs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Regions (stub)
    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("regions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("orgs")
    # Drop the enum type created by the raw SQL in upgrade()
    op.execute("DROP TYPE user_role")