"""Add document_analysis.metadata JSONB for ratecon page_count.

Revision ID: 20260723_01
Revises: 20260707_01
Create Date: 2026-07-23

Stores side-channel fields such as ``page_count`` used by POD ratecon-page
strip (FP-155). Extraction payloads remain in ``results``.
"""

from __future__ import annotations

from alembic import op

revision = "20260723_01"
down_revision = "20260707_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE document_analysis "
        "ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE document_analysis DROP COLUMN IF EXISTS metadata")
