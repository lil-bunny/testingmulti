"""Add driver-assignment lifecycle sub-statuses and workflow run event types.

Revision ID: 20260623_01
Revises: 20260622_01
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op

revision = "20260623_01"
down_revision = "20260622_01"
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
    # PostgreSQL cannot drop a single enum value. Recreate the types only if no
    # rows reference the driver-assignment values (otherwise downgrade will fail).
    op.execute(
        """
        CREATE TYPE lifecycle_sub_status_prev AS ENUM (
            'none',
            'tender_created',
            'tender_sent_to_tenant',
            'tender_sent_to_carrier',
            'reminder_1_sent',
            'reminder_2_sent',
            'accepted',
            'rejected',
            'do_nothing',
            'escalated',
            'reminder_3_sent',
            'pod_started',
            'ratecon_started',
            'document_uploaded',
            'document_processed',
            'uploaded_to_tms',
            'resolved_manually'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            ALTER COLUMN sub_status TYPE lifecycle_sub_status_prev
            USING sub_status::text::lifecycle_sub_status_prev
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN from_sub_status TYPE lifecycle_sub_status_prev
            USING from_sub_status::text::lifecycle_sub_status_prev,
            ALTER COLUMN to_sub_status TYPE lifecycle_sub_status_prev
            USING to_sub_status::text::lifecycle_sub_status_prev
        """
    )
    op.execute("DROP TYPE lifecycle_sub_status")
    op.execute(
        "ALTER TYPE lifecycle_sub_status_prev RENAME TO lifecycle_sub_status"
    )

    op.execute(
        """
        CREATE TYPE workflow_run_event_type_prev AS ENUM (
            'route_completed',
            'email_received',
            'reminder_due',
            'tender_created',
            'carrier_email_received',
            'ack_received',
            'escalation_due',
            'manual_pod_upload'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_runs
            ALTER COLUMN event_type TYPE workflow_run_event_type_prev
            USING event_type::text::workflow_run_event_type_prev
        """
    )
    op.execute("DROP TYPE workflow_run_event_type")
    op.execute(
        "ALTER TYPE workflow_run_event_type_prev RENAME TO workflow_run_event_type"
    )
