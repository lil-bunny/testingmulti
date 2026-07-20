"""Add appointment_customer_reply_received workflow run event type.

Revision ID: 20260721_01
Revises: 20260720_01
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op

revision = "20260721_01"
down_revision = "20260720_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS "
            "'appointment_customer_reply_received'"
        )


def downgrade() -> None:
    pass
