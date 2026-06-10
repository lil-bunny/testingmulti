"""Add pod_lifecycle sub-status enum values.

Revision ID: 20260605_06
Revises: 20260605_05
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_06"
down_revision: Union[str, Sequence[str], None] = "20260605_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'pod_started'"
    )
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'reminder_3_sent'"
    )


def downgrade() -> None:
    # Postgres does not support removing enum values safely.
    pass
