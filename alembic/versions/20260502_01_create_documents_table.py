"""create documents table (POD / ratecon artifact rows)

Revision ID: 20260502_01
Revises: 20260501_01
Create Date: 2026-05-02

Schema decisions (POD DB design chat a70ecf21-b177-4018-abf9-2a6fd53cd89b):
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260502_01"
down_revision: Union[str, Sequence[str], None] = "20260501_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # file name is type_attachmentId_shipId.extension
    # Create the ENUM for type
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_type') THEN
                CREATE TYPE document_type AS ENUM ('pod_attachment', 'pod_merged_final', 'ratecon');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            type document_type NOT NULL,
            shipment_id TEXT NOT NULL,
            object_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_shipment_id ON documents(shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(type)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_object_key ON documents(object_key)"
    )

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TYPE IF EXISTS document_type")