"""Rename document columns; document_id UUID FK; documents.id UUID.

Revision ID: 20260609_03
Revises: 20260609_02
Create Date: 2026-06-09

- documents.object_key -> storage_key
- document_analysis.findings -> results
- document_analysis.attachments_used -> document_id (nullable UUID FK)
- documents.id TEXT -> UUID
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260609_03"
down_revision: Union[str, Sequence[str], None] = "20260609_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(*, table: str, column: str) -> bool:
    return bool(
        op.get_bind()
        .execute(
            __import__("sqlalchemy").text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table
                  AND column_name = :column
                """
            ),
            {"table": table, "column": column},
        )
        .scalar()
    )


def upgrade() -> None:
    # documents: object_key -> storage_key
    if _column_exists(table="documents", column="object_key"):
        op.execute("ALTER TABLE documents RENAME COLUMN object_key TO storage_key")
    op.execute(
        "ALTER INDEX IF EXISTS uq_documents_object_key "
        "RENAME TO uq_documents_storage_key"
    )

    # document_analysis: findings -> results
    if _column_exists(table="document_analysis", column="findings"):
        op.execute("ALTER TABLE document_analysis RENAME COLUMN findings TO results")

    # attachments_used -> document_id (TEXT backfill, then UUID)
    if _column_exists(table="document_analysis", column="attachments_used"):
        if not _column_exists(table="document_analysis", column="document_id"):
            op.execute(
                "ALTER TABLE document_analysis ADD COLUMN document_id TEXT"
            )
        op.execute(
            """
            UPDATE document_analysis
            SET document_id = attachments_used->0->>'document_id'
            WHERE attachments_used IS NOT NULL
              AND jsonb_typeof(attachments_used) = 'array'
              AND jsonb_array_length(attachments_used) > 0
              AND attachments_used->0->>'document_id' IS NOT NULL
              AND btrim(attachments_used->0->>'document_id') <> ''
              AND document_id IS NULL
            """
        )
        op.execute("ALTER TABLE document_analysis DROP COLUMN attachments_used")

    op.execute(
        "ALTER TABLE document_analysis "
        "DROP CONSTRAINT IF EXISTS fk_document_analysis_document_id"
    )

    # documents.id TEXT -> UUID (must happen before document_id UUID FK)
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'documents'
              AND column_name = 'id'
              AND data_type = 'text'
          ) THEN
            ALTER TABLE documents
              ALTER COLUMN id TYPE uuid USING id::uuid;
          END IF;
        END $$;
        """
    )

    # document_id TEXT -> UUID
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'document_analysis'
              AND column_name = 'document_id'
              AND data_type = 'text'
          ) THEN
            ALTER TABLE document_analysis
              ALTER COLUMN document_id TYPE uuid USING document_id::uuid;
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE document_analysis
        ADD CONSTRAINT fk_document_analysis_document_id
        FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_analysis_document_id
        ON document_analysis (document_id)
        WHERE document_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_document_analysis_document_id")
    op.execute(
        "ALTER TABLE document_analysis "
        "DROP CONSTRAINT IF EXISTS fk_document_analysis_document_id"
    )

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'document_analysis'
              AND column_name = 'document_id'
              AND udt_name = 'uuid'
          ) THEN
            ALTER TABLE document_analysis
              ALTER COLUMN document_id TYPE text USING document_id::text;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'documents'
              AND column_name = 'id'
              AND udt_name = 'uuid'
          ) THEN
            ALTER TABLE documents
              ALTER COLUMN id TYPE text USING id::text;
          END IF;
        END $$;
        """
    )

    if not _column_exists(table="document_analysis", column="attachments_used"):
        op.execute(
            "ALTER TABLE document_analysis ADD COLUMN attachments_used JSONB"
        )
    if _column_exists(table="document_analysis", column="document_id"):
        op.execute("ALTER TABLE document_analysis DROP COLUMN document_id")

    if _column_exists(table="document_analysis", column="results"):
        op.execute("ALTER TABLE document_analysis RENAME COLUMN results TO findings")

    op.execute(
        "ALTER INDEX IF EXISTS uq_documents_storage_key "
        "RENAME TO uq_documents_object_key"
    )
    if _column_exists(table="documents", column="storage_key"):
        op.execute("ALTER TABLE documents RENAME COLUMN storage_key TO object_key")
