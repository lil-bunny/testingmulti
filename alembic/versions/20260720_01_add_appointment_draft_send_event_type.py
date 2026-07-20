"""Add appointment_draft_send event type and awaiting_customer_reply sub-status.

Revision ID: 20260720_01
Revises: 20260719_01
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op

revision = "20260720_01"
down_revision = "20260719_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
            "'appointment_draft_send'"
        )
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'awaiting_customer_reply'"
        )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value.
    pass
