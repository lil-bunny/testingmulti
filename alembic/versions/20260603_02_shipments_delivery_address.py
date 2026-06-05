"""Add ``delivery_address`` JSONB to ``shipments``.

Revision ID: 20260603_02
Revises: 20260603_01
Create Date: 2026-06-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260603_02"
down_revision: Union[str, Sequence[str], None] = "20260603_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
            ADD COLUMN IF NOT EXISTS delivery_address JSONB
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS delivery_address")
