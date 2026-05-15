"""create data_imports table (raw import payloads per tenant)

Revision ID: 20260514_01
Revises: 20260509_01
Create Date: 2026-05-14
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260514_01"
down_revision: Union[str, Sequence[str], None] = "20260509_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_imports (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         uuid NOT NULL REFERENCES tenants(id),
            data_type         text NOT NULL,
            source_type       text NOT NULL,
            file_name         text,
            raw_data          jsonb NOT NULL,
            created_at        timestamptz DEFAULT now(),
            updated_at        timestamptz DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_imports")
