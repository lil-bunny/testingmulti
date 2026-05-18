"""Rename workflow_correlation to workflow_lifecycles; uuid PK; status columns.

Migrates lifecycle rows to ``workflow_lifecycles`` with UUID ``id``, optional
correlation columns, and lifecycle ``status``. ``tenant_id`` is migrated to UUID
(without FK) here — ``20260513_01`` attaches ``tenant_id REFERENCES tenants(id)``
and NOT NULL once ``tenants`` exists.

Revision ID: 20260508_01
Revises: 20260503_01
Create Date: 2026-05-08
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260508_01"
down_revision: Union[str, Sequence[str], None] = "20260503_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Use lifecycle table primary key id as lifecycle/thread id.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'workflow_correlation'
                  AND column_name = 'workflow_instance_id'
            ) THEN
                UPDATE workflow_correlation
                SET id = workflow_instance_id
                WHERE workflow_instance_id IS NOT NULL
                  AND id IS DISTINCT FROM workflow_instance_id;
            END IF;
        END $$;
        """
    )

    # 2) Rename table workflow_correlation -> workflow_lifecycles.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_correlation') IS NOT NULL
               AND to_regclass('public.workflow_lifecycles') IS NULL THEN
                ALTER TABLE workflow_correlation RENAME TO workflow_lifecycles;
            END IF;
        END $$;
        """
    )

    # 3) Shipment/email indexes; drop load_id index (column removed later).
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.idx_workflow_correlation_shipment_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_correlation_shipment_id RENAME TO idx_workflow_lifecycles_shipment_id;
            END IF;
            DROP INDEX IF EXISTS idx_workflow_correlation_load_id;
            DROP INDEX IF EXISTS idx_workflow_lifecycles_load_id;
            IF to_regclass('public.idx_workflow_correlation_email_thread_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_correlation_email_thread_id RENAME TO idx_workflow_lifecycles_email_thread_id;
            END IF;
        END $$;
        """
    )

    # 4) Drop unique constraint/index on workflow_instance_id, then drop the column.
    op.execute(
        """
        DO $$
        DECLARE
            c RECORD;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles'
                  AND column_name = 'workflow_instance_id'
            ) THEN
                FOR c IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'workflow_lifecycles'::regclass
                      AND contype = 'u'
                      AND pg_get_constraintdef(oid) ILIKE '%workflow_instance_id%'
                LOOP
                    EXECUTE format('ALTER TABLE workflow_lifecycles DROP CONSTRAINT %I', c.conname);
                END LOOP;

                FOR c IN
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = 'workflow_lifecycles'
                      AND indexdef ILIKE '%workflow_instance_id%'
                LOOP
                    EXECUTE format('DROP INDEX IF EXISTS %I', c.indexname);
                END LOOP;

                ALTER TABLE workflow_lifecycles DROP COLUMN workflow_instance_id;
            END IF;
        END $$;
        """
    )

    # 5) Rename workflow_runs.workflow_instance_id -> workflow_lifecycle_id.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'workflow_runs'
                  AND column_name = 'workflow_instance_id'
            ) THEN
                ALTER TABLE workflow_runs
                RENAME COLUMN workflow_instance_id TO workflow_lifecycle_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.uq_workflow_runs_wi_entry_event') IS NOT NULL THEN
                ALTER INDEX uq_workflow_runs_wi_entry_event RENAME TO uq_workflow_runs_wl_entry_event;
            END IF;
        END $$;
        """
    )

    # 6) Drop load correlation column from lifecycles.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NOT NULL THEN
                ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS load_id;
            END IF;
        END $$;
        """
    )

    # 7) Lifecycle status columns.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles' AND column_name = 'status'
            ) THEN
                ALTER TABLE workflow_lifecycles
                    ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles' AND column_name = 'sub_status'
            ) THEN
                ALTER TABLE workflow_lifecycles ADD COLUMN sub_status TEXT;
            END IF;
        END $$;
        """
    )

    # 8) Migrate tenant_id to uuid when present as text; FK is added in 20260513_01.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
                  AND column_name = 'tenant_id'
                  AND data_type <> 'uuid'
            ) THEN
                DROP INDEX IF EXISTS idx_workflow_lifecycles_tenant_id;
                ALTER TABLE workflow_lifecycles
                  ALTER COLUMN tenant_id TYPE uuid
                  USING NULLIF(btrim(tenant_id::text), '')::uuid;
                CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tenant_id
                  ON workflow_lifecycles (tenant_id);
            ELSIF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workflow_lifecycles'
                  AND column_name = 'tenant_id'
            ) THEN
                ALTER TABLE workflow_lifecycles ADD COLUMN tenant_id uuid;
                CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tenant_id
                  ON workflow_lifecycles (tenant_id);
            END IF;
        END $$;
        """
    )

    # 9) FK types: drop FK workflow_runs -> lifecycles, convert both key columns to uuid.
    op.execute(
        """
        DO $$
        DECLARE
            c RECORD;
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs DROP CONSTRAINT fk_workflow_runs_workflow_lifecycle_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles'
                  AND column_name = 'id'
                  AND data_type <> 'uuid'
            ) THEN
                FOR c IN
                    SELECT conname FROM pg_constraint
                    WHERE contype = 'p' AND conrelid = 'workflow_lifecycles'::regclass
                LOOP
                    EXECUTE format('ALTER TABLE workflow_lifecycles DROP CONSTRAINT %I', c.conname);
                END LOOP;

                ALTER TABLE workflow_lifecycles
                  ALTER COLUMN id TYPE uuid USING btrim(id::text)::uuid;
                ALTER TABLE workflow_lifecycles ADD PRIMARY KEY (id);
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_runs'
                  AND column_name = 'workflow_lifecycle_id'
                  AND data_type <> 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                  ALTER COLUMN workflow_lifecycle_id TYPE uuid USING btrim(workflow_lifecycle_id::text)::uuid;
            END IF;
        END $$;
        """
    )

    # 10) Recreate FK from workflow_runs to workflow_lifecycles.
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

    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'public'
                AND table_name = 'workflow_lifecycles'
                AND column_name = 'id'
                AND data_type = 'uuid'
          ) THEN
              ALTER TABLE workflow_lifecycles
                  ALTER COLUMN id SET DEFAULT gen_random_uuid();
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Best-effort partial revert (lifecycles back toward workflow_correlation shape)."""

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

    op.execute(
        """
        DO $$
        DECLARE
            c RECORD;
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NULL THEN
                RETURN;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_runs'
                  AND column_name = 'workflow_lifecycle_id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE workflow_runs
                  ALTER COLUMN workflow_lifecycle_id TYPE text USING workflow_lifecycle_id::text;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles'
                  AND column_name = 'id'
                  AND data_type = 'uuid'
            ) THEN
                FOR c IN
                    SELECT conname FROM pg_constraint
                    WHERE contype = 'p' AND conrelid = 'workflow_lifecycles'::regclass
                LOOP
                    EXECUTE format('ALTER TABLE workflow_lifecycles DROP CONSTRAINT %I', c.conname);
                END LOOP;
                ALTER TABLE workflow_lifecycles ALTER COLUMN id DROP DEFAULT;
                ALTER TABLE workflow_lifecycles
                  ALTER COLUMN id TYPE text USING id::text;
                ALTER TABLE workflow_lifecycles ADD PRIMARY KEY (id);
            END IF;

            ALTER TABLE workflow_lifecycles ADD COLUMN IF NOT EXISTS load_id TEXT;
            ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS status;
            ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS sub_status;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_lifecycles'
                  AND column_name = 'tenant_id'
                  AND data_type = 'uuid'
            ) THEN
                DROP INDEX IF EXISTS idx_workflow_lifecycles_tenant_id;
                ALTER TABLE workflow_lifecycles
                  ALTER COLUMN tenant_id TYPE text USING tenant_id::text;
                CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tenant_id
                  ON workflow_lifecycles (tenant_id);
            END IF;
        END $$;
        """
    )

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

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'workflow_lifecycles'
                      AND column_name = 'workflow_instance_id'
               ) THEN
                ALTER TABLE workflow_lifecycles ADD COLUMN workflow_instance_id TEXT;
                UPDATE workflow_lifecycles
                SET workflow_instance_id = id;
                ALTER TABLE workflow_lifecycles
                ALTER COLUMN workflow_instance_id SET NOT NULL;
                ALTER TABLE workflow_lifecycles
                ADD CONSTRAINT uq_workflow_lifecycles_workflow_instance_id UNIQUE (workflow_instance_id);
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.idx_workflow_lifecycles_shipment_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_lifecycles_shipment_id RENAME TO idx_workflow_correlation_shipment_id;
            END IF;
            IF to_regclass('public.idx_workflow_lifecycles_email_thread_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_lifecycles_email_thread_id RENAME TO idx_workflow_correlation_email_thread_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_lifecycles') IS NOT NULL
               AND to_regclass('public.workflow_correlation') IS NULL THEN
                ALTER TABLE workflow_lifecycles RENAME TO workflow_correlation;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'workflow_runs'
                  AND column_name = 'workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs RENAME COLUMN workflow_lifecycle_id TO workflow_instance_id;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.uq_workflow_runs_wl_entry_event') IS NOT NULL THEN
                ALTER INDEX uq_workflow_runs_wl_entry_event RENAME TO uq_workflow_runs_wi_entry_event;
            END IF;
        END $$;
        """
    )
