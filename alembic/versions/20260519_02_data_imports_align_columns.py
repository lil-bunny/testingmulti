"""Align ``data_imports`` with load-tendering ingest shape (fix partial v2 table).

Revision ID: 20260519_02
Revises: 20260519_01
Create Date: 2026-05-19

Earlier ``8bf7afa5eaad`` used ``CREATE TABLE IF NOT EXISTS`` with only ``id`` and
``created_at``; ``20260514_01`` did not add columns when the table already existed.
This revision adds missing columns idempotently.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260519_02"
down_revision: Union[str, Sequence[str], None] = "20260519_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE data_imports
            ADD COLUMN IF NOT EXISTS tenant_id UUID,
            ADD COLUMN IF NOT EXISTS data_type TEXT,
            ADD COLUMN IF NOT EXISTS source_type TEXT,
            ADD COLUMN IF NOT EXISTS file_name TEXT,
            ADD COLUMN IF NOT EXISTS raw_data JSONB,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
        """
    )
    op.execute(
        """
        UPDATE data_imports
        SET
            data_type = COALESCE(data_type, 'load_tender'),
            source_type = COALESCE(source_type, 'email'),
            raw_data = COALESCE(raw_data, '{}'::jsonb),
            updated_at = COALESCE(updated_at, created_at, NOW())
        WHERE data_type IS NULL
           OR source_type IS NULL
           OR raw_data IS NULL
           OR updated_at IS NULL;
        """
    )
    op.execute(
        """
        UPDATE data_imports di
        SET tenant_id = t.id
        FROM (SELECT id FROM tenants ORDER BY created_at NULLS LAST, id LIMIT 1) t
        WHERE di.tenant_id IS NULL;
        """
    )
    op.execute("DELETE FROM data_imports WHERE tenant_id IS NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'data_imports_tenant_id_fkey'
            ) THEN
                ALTER TABLE data_imports
                    ADD CONSTRAINT data_imports_tenant_id_fkey
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id);
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'data_imports'
                  AND column_name = 'tenant_id'
                  AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE data_imports
                    ALTER COLUMN tenant_id SET NOT NULL,
                    ALTER COLUMN data_type SET NOT NULL,
                    ALTER COLUMN source_type SET NOT NULL,
                    ALTER COLUMN raw_data SET NOT NULL;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        ALTER TABLE data_imports
            ALTER COLUMN created_at SET DEFAULT NOW(),
            ALTER COLUMN updated_at SET DEFAULT NOW();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE data_imports
            DROP CONSTRAINT IF EXISTS data_imports_tenant_id_fkey;
        """
    )
    op.execute(
        """
        ALTER TABLE data_imports
            DROP COLUMN IF EXISTS tenant_id,
            DROP COLUMN IF EXISTS data_type,
            DROP COLUMN IF EXISTS source_type,
            DROP COLUMN IF EXISTS file_name,
            DROP COLUMN IF EXISTS raw_data,
            DROP COLUMN IF EXISTS updated_at;
        """
    )
