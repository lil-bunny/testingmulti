"""Create ``tenants`` table (referenced by ``data_imports``, ``tenders``, OAuth).

Prior migrations assumed ``tenants`` already existed when adding FK constraints.
This revision creates it before ``20260514_01``.

Revision ID: 20260513_01
Revises: 20260509_01
Create Date: 2026-05-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260513_01"
down_revision: Union[str, Sequence[str], None] = "20260509_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name          text NOT NULL,
            slug          text UNIQUE NOT NULL,
            settings      jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at    timestamptz DEFAULT now(),
            updated_at    timestamptz DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenants")
