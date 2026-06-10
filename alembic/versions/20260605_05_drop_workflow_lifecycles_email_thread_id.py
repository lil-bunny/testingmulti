"""Drop ``workflow_lifecycles.email_thread_id`` (thread on ``communications``).

Revision ID: 20260605_05
Revises: 20260605_04
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_05"
down_revision: Union[str, Sequence[str], None] = "20260605_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_email_thread_id")
    op.execute("ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS email_thread_id")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
        ADD COLUMN IF NOT EXISTS email_thread_id TEXT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_email_thread_id
        ON workflow_lifecycles (email_thread_id)
        """
    )
