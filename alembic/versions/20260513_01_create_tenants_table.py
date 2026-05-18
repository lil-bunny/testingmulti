"""Create ``tenants`` table and enforce tenant FK on ``workflow_lifecycles``.

Creates ``tenants`` before revisions that attach FK constraints (for example ``data_imports``).
Additionally sets ``workflow_lifecycles.tenant_id`` NOT NULL and adds
``FOREIGN KEY (tenant_id) REFERENCES tenants(id)`` after both tables exist.

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
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
            ) THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
                  AND column_name = 'tenant_id'
                  AND data_type = 'uuid'
            ) THEN
                RETURN;
            END IF;

            IF EXISTS (SELECT 1 FROM workflow_lifecycles WHERE tenant_id IS NULL) THEN
                RAISE EXCEPTION
                    'Cannot add tenant FK: workflow_lifecycles contains rows where tenant_id is NULL '
                    '(backfill tenant_id UUIDs before running this revision)';
            END IF;

            ALTER TABLE workflow_lifecycles
                ALTER COLUMN tenant_id SET NOT NULL;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_lifecycles_tenant_id'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    ADD CONSTRAINT fk_workflow_lifecycles_tenant_id
                    FOREIGN KEY (tenant_id) REFERENCES tenants (id);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_lifecycles_tenant_id'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    DROP CONSTRAINT fk_workflow_lifecycles_tenant_id;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
                  AND column_name = 'tenant_id'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    ALTER COLUMN tenant_id DROP NOT NULL;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS tenants")
