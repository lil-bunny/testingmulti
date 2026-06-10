"""Move weight_unit from tenders to tender_products (Ship Schedule ME per line).

Revision ID: 20260610_03
Revises: 20260610_02
Create Date: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260610_03"
down_revision: Union[str, Sequence[str], None] = "20260610_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tender_products
            ADD COLUMN IF NOT EXISTS weight_unit weight_unit
        """
    )
    op.execute(
        """
        UPDATE tender_products tp
        SET weight_unit = t.weight_unit
        FROM tenders t
        WHERE tp.tender_id = t.id
          AND t.weight_unit IS NOT NULL
          AND tp.weight_unit IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
            DROP COLUMN IF EXISTS weight_unit
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
            ADD COLUMN IF NOT EXISTS weight_unit weight_unit
        """
    )
    op.execute(
        """
        UPDATE tenders t
        SET weight_unit = sub.weight_unit
        FROM (
            SELECT DISTINCT ON (tender_id)
                tender_id,
                weight_unit
            FROM tender_products
            WHERE weight_unit IS NOT NULL
            ORDER BY tender_id, created_at ASC, id ASC
        ) sub
        WHERE t.id = sub.tender_id
          AND t.weight_unit IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tender_products
            DROP COLUMN IF EXISTS weight_unit
        """
    )
