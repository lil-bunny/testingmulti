"""Unique (tenant_id, order_number) on tenders for idempotent ingest.

Revision ID: 20260522_03
Revises: 20260522_02
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260522_03"
down_revision: Union[str, Sequence[str], None] = "20260522_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
        ADD CONSTRAINT tenders_tenant_order_number_unique
        UNIQUE (tenant_id, order_number)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
        DROP CONSTRAINT IF EXISTS tenders_tenant_order_number_unique
        """
    )
