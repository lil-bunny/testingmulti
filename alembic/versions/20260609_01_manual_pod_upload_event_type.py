"""Add manual_pod_upload to workflow_run_event_type enum.

Revision ID: 20260609_01
Revises: 20260608_01
Create Date: 2026-06-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260609_01"
down_revision: Union[str, Sequence[str], None] = "20260608_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS 'manual_pod_upload'"
    )


def downgrade() -> None:
    pass
