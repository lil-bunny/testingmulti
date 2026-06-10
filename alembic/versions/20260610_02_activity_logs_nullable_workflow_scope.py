"""Allow NULL workflow_run_id on activity_logs for portal lifecycle-scoped actions.

Portal acknowledge/resolve set workflow_lifecycle_id and leave workflow_run_id NULL.
workflow_lifecycle_id stays NOT NULL.

Revision ID: 20260610_02
Revises: 20260610_01
Create Date: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260610_02"
down_revision: Union[str, Sequence[str], None] = "20260610_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN workflow_run_id DROP NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM activity_logs
        WHERE workflow_run_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN workflow_run_id SET NOT NULL
        """
    )
