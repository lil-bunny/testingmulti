"""Add cancelled to lifecycle_sub_status enum."""

from __future__ import annotations

from alembic import op

revision = "20260621_01"
down_revision = "20260620_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'cancelled'"
    )


def downgrade() -> None:
    pass
