"""Add shipments.driver_details JSONB column.

Revision ID: 20260626_01
Revises: 20260623_01
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op

revision = "20260626_01"
down_revision = "20260623_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
        ADD COLUMN IF NOT EXISTS driver_details JSONB NOT NULL
        DEFAULT '{"name": null, "phone": null}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS driver_details")
