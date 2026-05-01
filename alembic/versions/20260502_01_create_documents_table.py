"""create documents table (POD / ratecon artifact rows)

Revision ID: 20260502_01
Revises: 20260501_01
Create Date: 2026-05-02

Schema decisions (POD DB design chat a70ecf21-b177-4018-abf9-2a6fd53cd89b):

- url is non nullable for S3 backed artifacts
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
            url TEXT,
            email_id TEXT,
            attachment_id TEXT,
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
        """
        CREATE INDEX IF NOT EXISTS idx_documents_unipile_source
        ON documents(email_id, attachment_id)
        WHERE email_id IS NOT NULL AND attachment_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TYPE IF EXISTS document_type")