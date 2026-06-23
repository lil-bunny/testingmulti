"""Add driver-assignment lifecycle sub-statuses and workflow run event types.

Revision ID: 20260619_01
Revises: 20260618_01
Create Date: 2026-06-19

For databases that already ran ``20260525_01_initial_schema`` before these
enum members existed. Fresh installs get the same values from the initial
schema; ``IF NOT EXISTS`` keeps this idempotent.
"""

from __future__ import annotations

from alembic import op

revision = "20260619_01"
down_revision = "20260618_01"
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
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS "
        "'driver_details_email_received'"
    )
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'details_received'"
    )
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'cancelled'"
    )
    op.execute(
        "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
        "'ratecon_completed'"
    )
    op.execute(
        "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
        "'driver_details_email_received'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
