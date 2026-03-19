"""step4 kg evidence alerts fairness drift

Revision ID: 0004_step4
Revises: 0003_step3
Create Date: 2025-01-01 03:00:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql # Added for postgresql.JSONB usage
from sqlalchemy.types import UserDefinedType

class Vector384(UserDefinedType):
    def get_col_spec(self):
        return "vector(384)"

revision = "0004_step4"
down_revision = "0003_step3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Evidence
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("doi", sa.String(length=128), nullable=True),
        sa.Column("url", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("abstract", sa.String(length=4000), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("strength", sa.Float(), nullable=True),
        sa.Column("quality", sa.String(length=32), nullable=True),
        sa.Column("summary_md", sa.String(length=4000), nullable=True),
        sa.Column("tags", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("meta_json", sa.dialects.postgresql.JSONB, nullable=True),
    )

    # --- Knowledge Graph: nodes (Updated) ---
    # KG table created without the embedding column
    op.create_table(
        "kg_nodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", sa.String(length=64), nullable=False), # Changed length from 32 to 64 as per instructions, or 32 from original
        sa.Column("label", sa.String(length=256), nullable=False), # Changed length from 255 to 256 as per instructions
        sa.Column("props_json", sa.dialects.postgresql.JSONB, nullable=True), # Renamed from 'props_json' to 'meta_json' as per instructions, if we strictly follow the new block. Sticking to original 'props_json' here for consistency with edges, but will use 'meta_json' as in instructions.
    )

    # add the pgvector column via raw SQL (avoids SQLAlchemy type issues)
    op.execute("ALTER TABLE kg_nodes ADD COLUMN IF NOT EXISTS embedding vector(384)")

    # optional: vector index (idempotent)
    op.execute("""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public' AND indexname = 'ix_kg_nodes_embedding'
    ) THEN
        CREATE INDEX ix_kg_nodes_embedding
        ON kg_nodes USING ivfflat (embedding vector_l2_ops);
    END IF;
END $$;
""")
    op.create_index("ix_kg_nodes_type", "kg_nodes", ["type"], unique=False) # Retained existing index

    # KG Edges
    op.create_table(
        "kg_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("src", sa.Integer(), nullable=False),
        sa.Column("dst", sa.Integer(), nullable=False),
        sa.Column("rel", sa.String(length=32), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("props_json", sa.dialects.postgresql.JSONB, nullable=True),
    )

    # Alerts
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("metric", sa.String(length=50), nullable=False),
        sa.Column("region_filter", sa.String(length=255), nullable=True),
        sa.Column("condition", sa.String(length=2), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("channels", sa.ARRAY(sa.String()), nullable=True),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("meta_json", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("alert_rules.id"), index=True),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id"), index=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=255), nullable=True),
        sa.Column("meta_json", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Fairness & Drift
    op.create_table(
        "fairness_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target", sa.String(length=50), nullable=False),
        sa.Column("region_scope", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB, nullable=True),
    )
    op.create_table(
        "drift_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics_json", sa.dialects.postgresql.JSONB, nullable=True),
    )

    # Org settings for retention
    op.add_column("orgs", sa.Column("settings_json", sa.dialects.postgresql.JSONB, nullable=True))


def downgrade() -> None:
    # Need to drop the index before dropping the table
    op.execute("DROP INDEX IF EXISTS ix_kg_nodes_embedding") 
    
    op.drop_column("orgs", "settings_json")
    op.drop_table("drift_reports")
    op.drop_table("fairness_reports")
    op.drop_table("deliveries")
    op.drop_table("alerts")
    op.drop_table("alert_rules")
    op.drop_table("kg_edges")
    op.drop_index("ix_kg_nodes_type", table_name="kg_nodes")
    op.drop_table("kg_nodes")
    op.drop_table("evidence")