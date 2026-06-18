"""Add driver_assignment_started and reminder_4_sent to lifecycle_sub_status enum."""

from __future__ import annotations

from alembic import op

revision = "20260617_01"
down_revision = "20260616_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS "
        "'driver_assignment_started'"
    )
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'reminder_4_sent'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
