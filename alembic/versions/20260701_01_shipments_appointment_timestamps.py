"""Shipment appointment timestamps and drop legacy DA sub-status enum values.

Revision ID: 20260701_01
Revises: 20260630_01
Create Date: 2026-07-01

Removes unused ``lifecycle_sub_status`` values ``details_received`` and
``driver_details_email_received`` (sub-status only; workflow event type unchanged).
Upgrade fails if any row still references those sub-status values.
"""

from __future__ import annotations

from alembic import op

revision = "20260701_01"
down_revision = "20260630_01"
branch_labels = None
depends_on = None

# Matches ``StatusSubType`` in app/models/status.py (no legacy DA sub-statuses).
_LIFECYCLE_SUB_STATUS_WITHOUT_LEGACY = (
    "none",
    "tender_created",
    "tender_sent_to_tenant",
    "tender_sent_to_carrier",
    "reminder_1_sent",
    "reminder_2_sent",
    "reminder_3_sent",
    "reminder_4_sent",
    "accepted",
    "rejected",
    "do_nothing",
    "escalated",
    "pod_started",
    "driver_assignment_started",
    "ratecon_started",
    "document_uploaded",
    "document_processed",
    "uploaded_to_tms",
    "cancelled",
    "resolved_manually",
)

# Post-20260623_01 labels (legacy sub-status values restored on downgrade only).
_LIFECYCLE_SUB_STATUS_WITH_LEGACY = _LIFECYCLE_SUB_STATUS_WITHOUT_LEGACY + (
    "driver_details_email_received",
    "details_received",
)


def _enum_labels_sql(labels: tuple[str, ...]) -> str:
    return ",\n            ".join(f"'{label}'" for label in labels)


def _swap_lifecycle_sub_status(labels: tuple[str, ...]) -> None:
    op.execute(
        f"""
        CREATE TYPE lifecycle_sub_status_new AS ENUM (
            {_enum_labels_sql(labels)}
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            ALTER COLUMN sub_status TYPE lifecycle_sub_status_new
            USING sub_status::text::lifecycle_sub_status_new
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN from_sub_status TYPE lifecycle_sub_status_new
            USING from_sub_status::text::lifecycle_sub_status_new,
            ALTER COLUMN to_sub_status TYPE lifecycle_sub_status_new
            USING to_sub_status::text::lifecycle_sub_status_new
        """
    )
    op.execute("DROP TYPE lifecycle_sub_status")
    op.execute("ALTER TYPE lifecycle_sub_status_new RENAME TO lifecycle_sub_status")


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
        ADD COLUMN IF NOT EXISTS pickup_date TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS pickup_timezone TEXT,
        ADD COLUMN IF NOT EXISTS delivery_timezone TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE shipments
        ALTER COLUMN delivery_date TYPE TIMESTAMPTZ
        USING delivery_date::timestamptz
        """
    )
    _swap_lifecycle_sub_status(_LIFECYCLE_SUB_STATUS_WITHOUT_LEGACY)


def downgrade() -> None:
    _swap_lifecycle_sub_status(_LIFECYCLE_SUB_STATUS_WITH_LEGACY)
    op.execute(
        """
        ALTER TABLE shipments
        ALTER COLUMN delivery_date TYPE DATE
        USING delivery_date::date
        """
    )
    op.execute(
        """
        ALTER TABLE shipments
        DROP COLUMN IF EXISTS delivery_timezone,
        DROP COLUMN IF EXISTS pickup_timezone,
        DROP COLUMN IF EXISTS pickup_date
        """
    )
