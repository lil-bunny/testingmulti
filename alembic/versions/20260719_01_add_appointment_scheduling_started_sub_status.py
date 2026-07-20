"""Add appointment_scheduling_started lifecycle sub-status.

Revision ID: 20260719_01
Revises: 20260715_01
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op

revision = "20260719_01"
down_revision = "20260715_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'appointment_scheduling_started'"
        )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value.
    pass
