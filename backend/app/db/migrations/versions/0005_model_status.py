"""add status to model_versions

Revision ID: 0005_model_status
Revises: 0004_step4
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_model_status"
down_revision = "0004_step4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_versions",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.create_index("ix_model_versions_status", "model_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_versions_status", table_name="model_versions")
    op.drop_column("model_versions", "status")
