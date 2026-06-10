"""Documents storage_key + shipment FK; document_analysis FKs, results.

Revision ID: 20260609_01
Revises: 20260608_01
Create Date: 2026-06-09

Empty-database migration: no backfill. One raw SQL statement per schema change.

Changes both ``documents`` and ``document_analysis`` ``shipment_id`` from TEXT to
UUID with FK to ``shipments.id``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260609_01"
down_revision: Union[str, Sequence[str], None] = "20260608_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE documents
            RENAME COLUMN object_key TO storage_key
        """
    )
    op.execute(
        """
        ALTER INDEX uq_documents_object_key
            RENAME TO uq_documents_storage_key
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ALTER COLUMN id TYPE UUID USING id::uuid
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ALTER COLUMN shipment_id TYPE UUID USING shipment_id::uuid
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ADD CONSTRAINT documents_shipment_id_fkey
            FOREIGN KEY (shipment_id) REFERENCES shipments (id)
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            ALTER COLUMN shipment_id TYPE UUID USING shipment_id::uuid
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            ADD CONSTRAINT document_analysis_shipment_id_fkey
            FOREIGN KEY (shipment_id) REFERENCES shipments (id)
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            DROP COLUMN attachments_used
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            ADD COLUMN document_id UUID
            REFERENCES documents (id)
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            RENAME COLUMN findings TO results
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_analysis
            RENAME COLUMN results TO findings
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            DROP COLUMN document_id
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            ADD COLUMN attachments_used JSONB
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            DROP CONSTRAINT document_analysis_shipment_id_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE document_analysis
            ALTER COLUMN shipment_id TYPE TEXT USING shipment_id::text
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            DROP CONSTRAINT documents_shipment_id_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ALTER COLUMN shipment_id TYPE TEXT USING shipment_id::text
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            ALTER COLUMN id TYPE TEXT USING id::text
        """
    )
    op.execute(
        """
        ALTER INDEX uq_documents_storage_key
            RENAME TO uq_documents_object_key
        """
    )
    op.execute(
        """
        ALTER TABLE documents
            RENAME COLUMN storage_key TO object_key
        """
    )
