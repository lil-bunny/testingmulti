"""create document_analysis table (POD / ratecon / comparison results)

Revision ID: 20260502_02
Revises: 20260502_01
Create Date: 2026-05-02

One row per (shipment_id, analysis_type) for idempotent upserts.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260502_02"
down_revision: Union[str, Sequence[str], None] = "20260502_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Columns: id, shipment_id, analysis_type (enum), status, confidence_score,
    # llm_model (JSON), attachments_used (JSON), findings, created_at, updated_at
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_analysis_type') THEN
                CREATE TYPE document_analysis_type AS ENUM (
                    'ratecon_extraction',
                    'pod_extraction',
                    'pod_vs_ratecon_comparison'
                );
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_analysis (
            id TEXT PRIMARY KEY,
            shipment_id TEXT NOT NULL,
            analysis_type document_analysis_type NOT NULL,
            status TEXT,
            confidence_score DOUBLE PRECISION,
            llm_model JSONB,
            attachments_used JSONB,
            findings JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (shipment_id, analysis_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_analysis_shipment_id "
        "ON document_analysis(shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_analysis_analysis_type "
        "ON document_analysis(analysis_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_analysis")
    op.execute("DROP TYPE IF EXISTS document_analysis_type")
