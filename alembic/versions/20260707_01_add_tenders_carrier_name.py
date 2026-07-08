"""Add nullable ``carrier_name`` on ``tenders`` for FTL routing-guide assignment.

Revision ID: 20260707_01
Revises: 20260702_01
Create Date: 2026-07-07

Set on first inbound ``carrier_email_received`` (FTL only); overwritten on waterfall
advance when a later carrier responds. Partial index supports portal carrier stats.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260707_01"
down_revision: Union[str, Sequence[str], None] = "20260702_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
        ADD COLUMN IF NOT EXISTS carrier_name TEXT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_tenders_tenant_carrier_name_created_at
        ON tenders (tenant_id, carrier_name, created_at DESC)
        WHERE carrier_name IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenders_tenant_carrier_name_created_at")
    op.execute("ALTER TABLE tenders DROP COLUMN IF EXISTS carrier_name")
