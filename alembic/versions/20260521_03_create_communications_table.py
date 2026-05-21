"""Create communications table with channel and direction enums.

Revision ID: 20260521_03
Revises: 20260521_02, 8bf7afa5eaad
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_03"
down_revision: Union[str, Sequence[str], None] = ("20260521_02", "8bf7afa5eaad")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'communication_channel'
            ) THEN
                CREATE TYPE communication_channel AS ENUM ('email', 'slack', 'teams');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'communication_direction'
            ) THEN
                CREATE TYPE communication_direction AS ENUM ('inbound', 'outbound');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        CREATE TABLE communications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            channel communication_channel NOT NULL,
            direction communication_direction NOT NULL,

            external_id TEXT,
            thread_id TEXT,
            content TEXT,

            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_communications_tenant_id
            ON communications (tenant_id)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_communications_thread_id
            ON communications (thread_id)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_communications_external_id
            ON communications (external_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_communications_external_id")
    op.execute("DROP INDEX IF EXISTS idx_communications_thread_id")
    op.execute("DROP INDEX IF EXISTS idx_communications_tenant_id")
    op.execute("DROP TABLE IF EXISTS communications")
    op.execute("DROP TYPE IF EXISTS communication_direction")
    op.execute("DROP TYPE IF EXISTS communication_channel")
    op.execute("DROP TYPE IF EXISTS communication_direction_enum")
    op.execute("DROP TYPE IF EXISTS communication_channel_enum")
