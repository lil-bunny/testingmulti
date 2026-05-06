"""documents: add object_key for S3 key-only rows (e.g. ratecon)

Revision ID: 20260503_01
Revises: 20260502_02
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260503_01"
down_revision: Union[str, Sequence[str], None] = "20260502_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS object_key TEXT")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_object_key
        ON documents(object_key)
        WHERE object_key IS NOT NULL AND BTRIM(object_key) <> ''
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_documents_object_key")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS object_key")
