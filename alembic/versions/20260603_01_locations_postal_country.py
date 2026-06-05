"""Add ``postal_code`` and ``country`` to ``locations`` (merged locations migrations).

Revision ID: 20260603_01
Revises: 20260602_01
Create Date: 2026-06-03

Replaces the former chain ``20260603_01`` → ``20260603_02`` → ``20260603_03``
(country_code + source_id, drop source_id, postal_code + country rename).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260603_01"
down_revision: Union[str, Sequence[str], None] = "20260602_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: drop intermediate artifacts if an old split revision was applied.
    op.execute("DROP INDEX IF EXISTS locations_source_id_key")
    op.execute("DROP INDEX IF EXISTS locations_city_state_country_key")
    op.execute("ALTER TABLE locations DROP COLUMN IF EXISTS source_id")

    op.execute(
        """
        ALTER TABLE locations
            ADD COLUMN IF NOT EXISTS postal_code TEXT
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'locations'
                  AND column_name = 'country_code'
            ) THEN
                ALTER TABLE locations RENAME COLUMN country_code TO country;
            ELSIF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'locations'
                  AND column_name = 'country'
            ) THEN
                ALTER TABLE locations
                    ADD COLUMN country TEXT NOT NULL DEFAULT 'US';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        ALTER TABLE locations
            ALTER COLUMN country SET DEFAULT 'US'
        """
    )
    op.execute("DROP INDEX IF EXISTS locations_city_state_postal_country_key")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS locations_city_state_postal_country_key
            ON locations (city, state_code, postal_code, country)
            WHERE city IS NOT NULL AND state_code IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS locations_city_state_postal_country_key")
    op.execute(
        """
        ALTER TABLE locations
            DROP COLUMN IF EXISTS postal_code,
            DROP COLUMN IF EXISTS country
        """
    )
