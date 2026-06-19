"""Drop per-tenant order_number uniqueness (order rollover).

Revision ID: 20260618_01
Revises: 20260617_01
Create Date: 2026-06-18

- Drop ``tenders_tenant_order_number_unique`` so re-imports insert new tender rows.
- Add ``tenders_tenant_order_number_created_at_idx`` for latest-tender lookup.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260618_01"
down_revision: Union[str, Sequence[str], None] = "20260617_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
        DROP CONSTRAINT IF EXISTS tenders_tenant_order_number_unique
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS tenders_tenant_order_number_created_at_idx
        ON tenders (tenant_id, order_number, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS tenders_tenant_order_number_created_at_idx
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT tenders_tenant_order_number_unique
        UNIQUE (tenant_id, order_number)
        """
    )
