"""Rename workflow_correlation to workflow_lifecycles and lifecycle/run ids.

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

    # 3) Rename common index names if present.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.idx_workflow_correlation_shipment_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_correlation_shipment_id RENAME TO idx_workflow_lifecycles_shipment_id;
            END IF;
            IF to_regclass('public.idx_workflow_correlation_load_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_correlation_load_id RENAME TO idx_workflow_lifecycles_load_id;
            END IF;
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

    # 6) Rename unique index on workflow_runs if present.
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

    # 7) Optional FK from workflow_runs to workflow_lifecycles.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.workflow_runs') IS NOT NULL
               AND to_regclass('public.workflow_lifecycles') IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
               ) THEN
                ALTER TABLE workflow_runs
                ADD CONSTRAINT fk_workflow_runs_workflow_lifecycle_id
                FOREIGN KEY (workflow_lifecycle_id)
                REFERENCES workflow_lifecycles(id)
                ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # 1) Drop FK if it exists.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_workflow_runs_workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs
                DROP CONSTRAINT fk_workflow_runs_workflow_lifecycle_id;
            END IF;
        END $$;
        """
    )

    # 2) Rename workflow_runs.workflow_lifecycle_id -> workflow_instance_id.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'workflow_runs'
                  AND column_name = 'workflow_lifecycle_id'
            ) THEN
                ALTER TABLE workflow_runs
                RENAME COLUMN workflow_lifecycle_id TO workflow_instance_id;
            END IF;
        END $$;
        """
    )

    # 3) Rename index back if present.
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

    # 4) Add workflow_instance_id back to workflow_correlation/workflow_lifecycles and backfill from id.
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

    # 5) Rename indexes back if present.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.idx_workflow_lifecycles_shipment_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_lifecycles_shipment_id RENAME TO idx_workflow_correlation_shipment_id;
            END IF;
            IF to_regclass('public.idx_workflow_lifecycles_load_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_lifecycles_load_id RENAME TO idx_workflow_correlation_load_id;
            END IF;
            IF to_regclass('public.idx_workflow_lifecycles_email_thread_id') IS NOT NULL THEN
                ALTER INDEX idx_workflow_lifecycles_email_thread_id RENAME TO idx_workflow_correlation_email_thread_id;
            END IF;
        END $$;
        """
    )

    # 6) Rename table back workflow_lifecycles -> workflow_correlation.
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
