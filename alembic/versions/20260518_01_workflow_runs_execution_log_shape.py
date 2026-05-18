"""Align ``workflow_runs`` with staging execution log shape (uuid keys, no ``shipment_id``).

Adds ``status`` / ``updated_at``, drops redundant ``shipment_id`` (infer via ``workflow_lifecycles``),
converts ``id`` and ``tenant_id`` to UUID, and attaches ``tenant_id`` FK to ``tenants`` when missing.
Also adds nullable ``workflow_lifecycles.tender_id`` FK to ``tenders``.

Revision ID: 20260518_01
Revises: 20260517_01
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260518_01"
down_revision: Union[str, Sequence[str], None] = "20260517_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT fk_workflow_runs_workflow_lifecycle_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_tenant_id'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT fk_workflow_runs_tenant_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'status'
            ) THEN
                ALTER TABLE workflow_runs ADD COLUMN status text;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'updated_at'
            ) THEN
                ALTER TABLE workflow_runs ADD COLUMN updated_at timestamptz;
            END IF;

            UPDATE workflow_runs
            SET updated_at = COALESCE(updated_at, created_at, NOW())
            WHERE updated_at IS NULL;

            ALTER TABLE workflow_runs
                ALTER COLUMN updated_at SET DEFAULT NOW();

            ALTER TABLE workflow_runs
                ALTER COLUMN updated_at SET NOT NULL;
        END $$;
        """
    )

    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS shipment_id")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'id'
                  AND data_type <> 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                    ALTER COLUMN id TYPE uuid USING btrim(id::text)::uuid;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                    ALTER COLUMN id SET DEFAULT gen_random_uuid();
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'tenant_id'
                  AND data_type <> 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                    ADD COLUMN IF NOT EXISTS __wr_tid_mig uuid;

                UPDATE workflow_runs
                SET __wr_tid_mig = btrim(tenant_id::text)::uuid
                WHERE __wr_tid_mig IS NULL
                  AND btrim(tenant_id::text) ~*
                      '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

                UPDATE workflow_runs wr
                SET __wr_tid_mig = t.id
                FROM tenants t
                WHERE wr.__wr_tid_mig IS NULL
                  AND lower(btrim(wr.tenant_id::text)) = lower(btrim(t.slug));

                IF EXISTS (SELECT 1 FROM workflow_runs WHERE __wr_tid_mig IS NULL) THEN
                    RAISE EXCEPTION
                        'workflow_runs migrate: unresolved tenant_id (not UUID-shaped and no tenants.slug)';
                END IF;

                ALTER TABLE workflow_runs DROP COLUMN tenant_id;
                ALTER TABLE workflow_runs RENAME COLUMN __wr_tid_mig TO tenant_id;
                ALTER TABLE workflow_runs ALTER COLUMN tenant_id SET NOT NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL
               OR to_regclass('public.workflow_lifecycles') IS NULL THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs
                    ADD CONSTRAINT fk_workflow_runs_workflow_lifecycle_id
                    FOREIGN KEY (workflow_lifecycle_id)
                    REFERENCES workflow_lifecycles (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL
               OR to_regclass('public.tenants') IS NULL THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_tenant_id'
            ) THEN
                ALTER TABLE workflow_runs
                    ADD CONSTRAINT fk_workflow_runs_tenant_id
                    FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at
        ON workflow_runs (created_at DESC)
        """
    )

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
                  AND column_name = 'tender_id'
            ) THEN
                ALTER TABLE workflow_lifecycles ADD COLUMN tender_id uuid;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NULL
               OR to_regclass('public.tenders') IS NULL THEN
                RETURN;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_lifecycles_tender_id'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    ADD CONSTRAINT fk_workflow_lifecycles_tender_id
                    FOREIGN KEY (tender_id) REFERENCES tenders (id)
                    ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tender_id
        ON workflow_lifecycles (tender_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_tender_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_lifecycles_tender_id'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    DROP CONSTRAINT fk_workflow_lifecycles_tender_id;
            END IF;
        END $$;
        """
    )
    op.execute(
        "ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS tender_id"
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_tenant_id'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT fk_workflow_runs_tenant_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT fk_workflow_runs_workflow_lifecycle_id;
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS shipment_id TEXT")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NULL THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'tenant_id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                    ALTER COLUMN tenant_id TYPE text USING tenant_id::text;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_runs'
                  AND column_name = 'id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT workflow_runs_pkey;
                ALTER TABLE workflow_runs
                    ALTER COLUMN id TYPE text USING id::text;
                ALTER TABLE workflow_runs ADD PRIMARY KEY (id);
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS status")

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NOT NULL
               AND to_regclass('public.workflow_lifecycles') IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
               ) THEN
                ALTER TABLE workflow_runs
                    ADD CONSTRAINT fk_workflow_runs_workflow_lifecycle_id
                    FOREIGN KEY (workflow_lifecycle_id)
                    REFERENCES workflow_lifecycles (id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
