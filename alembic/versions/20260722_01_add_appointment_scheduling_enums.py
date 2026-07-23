"""Add appointment scheduling enums, turvo_pickup_changed, and proposed appointment columns.

Revision ID: 20260722_01
Revises: 20260707_01
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op

revision = "20260722_01"
down_revision = "20260707_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
            "'turvo_pickup_changed'"
        )
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'appointment_draft_created'"
        )
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'appointment_scheduling_started'"
        )
        op.execute(
            "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
            "'appointment_draft_send'"
        )
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'awaiting_customer_reply'"
        )
        op.execute(
            "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
            "'appointment_customer_reply_received'"
        )
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'appointment_scheduled'"
        )
    op.execute(
        """
        ALTER TABLE shipments
        ADD COLUMN IF NOT EXISTS proposed_pickup TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS proposed_delivery TIMESTAMPTZ
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
        DROP COLUMN IF EXISTS proposed_delivery,
        DROP COLUMN IF EXISTS proposed_pickup
        """
    )
    # PostgreSQL cannot drop a single enum value.
    pass
