"""Rename pod_requests -> workflow_duplicates and add tenant_name (+ composite PK).

Revision ID: 20260430_01
Revises: 20260429_01
Create Date: 2026-04-30
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260430_01"
down_revision: Union[str, Sequence[str], None] = "20260429_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename legacy table created by 20260429_01
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = 'pod_requests'
          ) AND NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = 'workflow_duplicates'
          ) THEN
            ALTER TABLE pod_requests RENAME TO workflow_duplicates;
          END IF;
        END $$;
        """
    )
    # Index name after rename — rename if legacy name exists
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'workflow_duplicates'
              AND indexname = 'idx_pod_requests_updated_at'
          ) THEN
            ALTER INDEX idx_pod_requests_updated_at RENAME TO idx_workflow_duplicates_updated_at;
          END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE workflow_duplicates ADD COLUMN IF NOT EXISTS tenant_name TEXT;
        UPDATE workflow_duplicates SET tenant_name = 't3ra' WHERE tenant_name IS NULL;
        ALTER TABLE workflow_duplicates ALTER COLUMN tenant_name SET NOT NULL;
        """
    )

    # Replace single-column shipment_id PK with (tenant_name, shipment_id)
    op.execute(
        """
        ALTER TABLE workflow_duplicates DROP CONSTRAINT IF EXISTS pod_requests_pkey;
        ALTER TABLE workflow_duplicates DROP CONSTRAINT IF EXISTS workflow_duplicates_pkey;
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_duplicates ADD PRIMARY KEY (tenant_name, shipment_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_duplicates DROP CONSTRAINT IF EXISTS workflow_duplicates_pkey;
        ALTER TABLE workflow_duplicates ADD PRIMARY KEY (shipment_id);
        ALTER TABLE workflow_duplicates DROP COLUMN IF EXISTS tenant_name;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = 'workflow_duplicates'
          ) THEN
            ALTER TABLE workflow_duplicates RENAME TO pod_requests;
          END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'pod_requests'
              AND indexname = 'idx_workflow_duplicates_updated_at'
          ) THEN
            ALTER INDEX idx_workflow_duplicates_updated_at RENAME TO idx_pod_requests_updated_at;
          END IF;
        END $$;
        """
    )
