"""Add ratecon lifecycle sub-status document_processed.

Revision ID: 20260605_04
Revises: 20260605_03
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_04"
down_revision: Union[str, Sequence[str], None] = "20260605_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'document_processed'"
    )


def downgrade() -> None:
    # Postgres does not support removing enum values safely.
    pass
