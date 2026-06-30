"""Add shipment appointment timestamps and timezones.

Revision ID: 20260630_01
Revises: 20260626_01
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op

revision = "20260630_01"
down_revision = "20260626_01"
branch_labels = None
depends_on = None


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


def downgrade() -> None:
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
