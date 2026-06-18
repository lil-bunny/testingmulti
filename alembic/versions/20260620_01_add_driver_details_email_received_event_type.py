"""Add driver_details_email_received to workflow_run_event_type enum."""

from __future__ import annotations

from alembic import op

revision = "20260620_01"
down_revision = "20260619_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
        "'driver_details_email_received'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
