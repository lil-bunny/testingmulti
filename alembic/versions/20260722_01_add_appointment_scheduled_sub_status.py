"""Add appointment_scheduled lifecycle sub-status.

Revision ID: 20260722_01
Revises: 20260721_01
Create Date: 2026-07-22
"""

from __future__ import annotations

from alembic import op

revision = "20260722_01"
down_revision = "20260721_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'appointment_scheduled'"
        )


def downgrade() -> None:
    pass
