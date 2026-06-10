"""Drop redundant document_analysis.status column.

Revision ID: 20260609_04
Revises: 20260609_03
Create Date: 2026-06-09

Cache readiness is determined by results.extracted_fields, not a separate status column.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260609_04"
down_revision: Union[str, Sequence[str], None] = "20260609_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_analysis DROP COLUMN IF EXISTS status")


def downgrade() -> None:
    op.execute("ALTER TABLE document_analysis ADD COLUMN IF NOT EXISTS status TEXT")
