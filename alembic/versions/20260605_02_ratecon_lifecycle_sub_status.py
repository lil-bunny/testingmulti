"""Add ratecon lifecycle sub-status enum values.

Revision ID: 20260605_02
Revises: 20260605_01
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_02"
down_revision: Union[str, Sequence[str], None] = "20260605_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'ratecon_started'"
    )
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'document_uploaded'"
    )


def downgrade() -> None:
    # Postgres does not support removing enum values safely.
    pass
