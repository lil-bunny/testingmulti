"""Drop lifecycle ``email_thread_id``; add comms thread+run index for Gelita correlation.

Revision ID: 20260608_01
Revises: 20260603_02
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260608_01"
down_revision: Union[str, Sequence[str], None] = "20260603_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_communications_tenant_thread_run
        ON communications (tenant_id, thread_id)
        WHERE workflow_run_id IS NOT NULL
        """
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_workflow_lifecycles_email_thread_id"
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            DROP COLUMN IF EXISTS email_thread_id
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            ADD COLUMN IF NOT EXISTS email_thread_id TEXT
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_email_thread_id "
        "ON workflow_lifecycles (email_thread_id)"
    )
    op.execute("DROP INDEX IF EXISTS idx_communications_tenant_thread_run")
