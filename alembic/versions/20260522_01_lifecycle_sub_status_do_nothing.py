"""Add ``do_nothing`` to ``lifecycle_sub_status`` for carrier ack no-op outcomes.

Revision ID: 20260522_01
Revises: 20260521_05
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260522_01"
down_revision: Union[str, Sequence[str], None] = "20260521_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_enum_value(enum_name: str, value: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TYPE {enum_name} ADD VALUE '{value}';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _add_enum_value("lifecycle_sub_status", "do_nothing")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
