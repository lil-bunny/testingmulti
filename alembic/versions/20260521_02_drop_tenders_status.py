"""Drop ``tenders.status``; lifecycle and activity_logs own progress.

Revision ID: 20260521_02
Revises: 20260521_01
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_02"
down_revision: Union[str, Sequence[str], None] = "20260521_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tenders_status")
    op.execute("ALTER TABLE tenders DROP COLUMN IF EXISTS status")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
            ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'processing'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenders_status
            ON tenders (status)
        """
    )
