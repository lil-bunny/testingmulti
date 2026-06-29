"""Add ``pack_codes.pack_type`` enum and ``pack_type_weight``.

Revision ID: 20260629_01
Revises: 20260626_01
Create Date: 2026-06-29
"""

from __future__ import annotations

from alembic import op

revision = "20260629_01"
down_revision = "20260626_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'pack_type'
            ) THEN
                CREATE TYPE pack_type AS ENUM (
                    'bag', 'drum', 'jar', 'case', 'pail'
                );
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE pack_codes
        ADD COLUMN IF NOT EXISTS pack_type pack_type
        """
    )
    op.execute(
        """
        ALTER TABLE pack_codes
        ADD COLUMN IF NOT EXISTS pack_type_weight NUMERIC
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE pack_codes
        DROP COLUMN IF EXISTS pack_type_weight
        """
    )
    op.execute(
        """
        ALTER TABLE pack_codes
        DROP COLUMN IF EXISTS pack_type
        """
    )
    op.execute("DROP TYPE IF EXISTS pack_type")
