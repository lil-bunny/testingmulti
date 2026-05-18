"""Add ``load_id`` back to ``workflow_lifecycles`` (nullable text + index).

Revision ID: 20260517_01
Revises: 20260516_01
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260517_01"
down_revision: Union[str, Sequence[str], None] = "20260516_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NULL THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
                  AND column_name = 'load_id'
            ) THEN
                ALTER TABLE workflow_lifecycles ADD COLUMN load_id text;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_load_id "
        "ON workflow_lifecycles (load_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_load_id")
    op.execute(
        """
        ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS load_id
        """
    )
