"""Add pod_lifecycle upload_to_tms sub-status enum value.

Revision ID: 20260608_01
Revises: 20260605_06
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260608_01"
down_revision: Union[str, Sequence[str], None] = "20260605_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'upload_to_tms'"
    )


def downgrade() -> None:
    pass
