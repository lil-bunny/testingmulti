"""Add weight_unit enum and column on tenders (Ship Schedule ME).

Revision ID: 20260608_01
Revises: 20260605_06
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260608_01"
down_revision: Union[str, Sequence[str], None] = "20260605_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE weight_unit AS ENUM ('kg', 'lbs');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
            ADD COLUMN IF NOT EXISTS weight_unit weight_unit
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenders DROP COLUMN IF EXISTS weight_unit")
    op.execute("DROP TYPE IF EXISTS weight_unit")
