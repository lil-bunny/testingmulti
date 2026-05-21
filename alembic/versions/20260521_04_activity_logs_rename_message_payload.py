"""Rename ``activity_logs.message`` / ``payload`` to match application code.

Revision ID: 20260521_04
Revises: 20260521_03
Create Date: 2026-05-21

Repository and ``ActivityLogService`` insert ``description`` and ``metadata``;
live DB still had legacy ``message`` and ``payload`` from ``8bf7afa5eaad``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_04"
down_revision: Union[str, Sequence[str], None] = "20260521_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_column_if_present(
    *,
    table: str,
    from_name: str,
    to_name: str,
) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table}'
                  AND column_name = '{from_name}'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table}'
                  AND column_name = '{to_name}'
            ) THEN
                ALTER TABLE {table} RENAME COLUMN {from_name} TO {to_name};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _rename_column_if_present(
        table="activity_logs",
        from_name="message",
        to_name="description",
    )
    _rename_column_if_present(
        table="activity_logs",
        from_name="payload",
        to_name="metadata",
    )


def downgrade() -> None:
    _rename_column_if_present(
        table="activity_logs",
        from_name="description",
        to_name="message",
    )
    _rename_column_if_present(
        table="activity_logs",
        from_name="metadata",
        to_name="payload",
    )
