"""migrate legacy workflow_correlation schema to explicit columns

Revision ID: 20260427_02
Revises: 20260427_01
Create Date: 2026-04-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260427_02"
down_revision: Union[str, Sequence[str], None] = "20260427_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add explicit columns expected by app/tools/workflow_correlation.py.
    op.execute(
        """
        ALTER TABLE workflow_correlation
            ADD COLUMN IF NOT EXISTS id TEXT,
            ADD COLUMN IF NOT EXISTS workflow_name TEXT,
            ADD COLUMN IF NOT EXISTS shipment_id TEXT,
            ADD COLUMN IF NOT EXISTS load_id TEXT,
            ADD COLUMN IF NOT EXISTS email_thread_id TEXT,
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
        """
    )

    # Backfill from legacy JSON payload if it exists.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'workflow_correlation'
                  AND column_name = 'payload'
            ) THEN
                UPDATE workflow_correlation
                SET
                    workflow_name = COALESCE(workflow_name, payload->>'workflow_name'),
                    shipment_id = COALESCE(shipment_id, payload->>'shipment_id'),
                    load_id = COALESCE(load_id, payload->>'load_id'),
                    email_thread_id = COALESCE(email_thread_id, payload->>'email_thread_id'),
                    updated_at = COALESCE(updated_at, NOW());
            END IF;
        END $$;
        """
    )

    # Generate IDs for pre-existing rows and fill required fields.
    op.execute(
        """
        UPDATE workflow_correlation
        SET id = COALESCE(id, md5(random()::text || clock_timestamp()::text)),
            workflow_name = COALESCE(workflow_name, 'pod_lifecycle'),
            created_at = COALESCE(created_at, NOW()),
            updated_at = COALESCE(updated_at, NOW());
        """
    )

    # Ensure constraints/indexes needed by lookup queries.
    op.execute(
        """
        DO $$
        DECLARE
            existing_pk_name text;
            existing_pk_is_id boolean := false;
        BEGIN
            SELECT c.conname
            INTO existing_pk_name
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE c.contype = 'p'
              AND t.relname = 'workflow_correlation'
              AND n.nspname = current_schema()
            LIMIT 1;

            IF existing_pk_name IS NOT NULL THEN
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    JOIN pg_attribute a
                      ON a.attrelid = t.oid
                     AND a.attnum = ANY(c.conkey)
                    WHERE c.conname = existing_pk_name
                      AND c.contype = 'p'
                      AND t.relname = 'workflow_correlation'
                      AND n.nspname = current_schema()
                      AND a.attname = 'id'
                      AND array_length(c.conkey, 1) = 1
                ) INTO existing_pk_is_id;
            END IF;

            IF existing_pk_name IS NOT NULL AND NOT existing_pk_is_id THEN
                EXECUTE format(
                    'ALTER TABLE workflow_correlation DROP CONSTRAINT %I',
                    existing_pk_name
                );
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE c.contype = 'p'
                  AND t.relname = 'workflow_correlation'
                  AND n.nspname = current_schema()
            ) THEN
                ALTER TABLE workflow_correlation
                ADD CONSTRAINT pk_workflow_correlation PRIMARY KEY (id);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_workflow_correlation_workflow_instance_id'
            ) THEN
                ALTER TABLE workflow_correlation
                ADD CONSTRAINT uq_workflow_correlation_workflow_instance_id
                UNIQUE (workflow_instance_id);
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_correlation_shipment_id ON workflow_correlation(shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_correlation_load_id ON workflow_correlation(load_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_correlation_email_thread_id ON workflow_correlation(email_thread_id)"
    )


def downgrade() -> None:
    # Revert schema additions for test environments.
    op.execute("DROP INDEX IF EXISTS idx_workflow_correlation_email_thread_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_correlation_load_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_correlation_shipment_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_workflow_correlation_workflow_instance_id'
            ) THEN
                ALTER TABLE workflow_correlation
                DROP CONSTRAINT uq_workflow_correlation_workflow_instance_id;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        DECLARE
            has_thread_id boolean := false;
        BEGIN
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'workflow_correlation'
                  AND column_name = 'thread_id'
            ) INTO has_thread_id;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'pk_workflow_correlation'
            ) THEN
                ALTER TABLE workflow_correlation
                DROP CONSTRAINT pk_workflow_correlation;
            END IF;

            IF has_thread_id THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'pk_workflow_correlation_thread_id'
                ) THEN
                    ALTER TABLE workflow_correlation
                    ADD CONSTRAINT pk_workflow_correlation_thread_id PRIMARY KEY (thread_id);
                END IF;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS email_thread_id")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS load_id")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS shipment_id")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS workflow_name")
    op.execute("ALTER TABLE workflow_correlation DROP COLUMN IF EXISTS id")
