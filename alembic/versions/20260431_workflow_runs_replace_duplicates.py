"""workflow_runs replaces workflow_duplicates / pod_requests lineage.

Stores rows for idempotency anchors (workflow_instance_id + entry event_types,
route_completed per shipment/load, reminders keyed by reminder_step).

Revision ID: 20260431
Revises: 20260430_01
Create Date: 2026-04-30
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260431"
down_revision: Union[str, Sequence[str], None] = "20260430_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            workflow_instance_id TEXT NOT NULL,
            shipment_id TEXT,
            load_id TEXT,
            reminder_step SMALLINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at
        ON workflow_runs (created_at DESC);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_wi_entry_event
        ON workflow_runs (workflow_instance_id, event_type)
        WHERE event_type NOT IN ('process_pod_followup', 'reminder_due');

        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_wi_reminder_step
        ON workflow_runs (workflow_instance_id, reminder_step)
        WHERE event_type = 'reminder_due';

        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_tenant_shipment_route_completed
        ON workflow_runs (tenant_id, shipment_id)
        WHERE event_type = 'route_completed' AND shipment_id IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_tenant_load_route_completed
        ON workflow_runs (tenant_id, load_id)
        WHERE event_type = 'route_completed' AND shipment_id IS NULL AND load_id IS NOT NULL;
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
            INSERT INTO workflow_runs (
                id, tenant_id, event_type, workflow_instance_id, shipment_id, load_id,
                reminder_step, created_at
            )
            SELECT DISTINCT ON (wd.tenant_name, wd.shipment_id)
                md5(random()::text || clock_timestamp()::text || wd.tenant_name || wd.shipment_id),
                wd.tenant_name,
                'route_completed',
                wd.workflow_instance_id,
                wd.shipment_id,
                NULL::text,
                NULL::smallint,
                COALESCE(wd.triggered_at, wd.created_at)
            FROM workflow_duplicates wd
            WHERE wd.is_pod_request_triggered = TRUE
            ORDER BY wd.tenant_name, wd.shipment_id, wd.triggered_at DESC NULLS LAST;

            EXECUTE 'DROP TABLE workflow_duplicates CASCADE';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_duplicates (
            tenant_name TEXT NOT NULL,
            shipment_id TEXT NOT NULL,
            workflow_instance_id TEXT NOT NULL,
            is_pod_request_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            triggered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (tenant_name, shipment_id)
        );
        CREATE INDEX IF NOT EXISTS idx_workflow_duplicates_updated_at
        ON workflow_duplicates(updated_at DESC);
        """
    )
    op.execute(
        """
        INSERT INTO workflow_duplicates (
            tenant_name,
            shipment_id,
            workflow_instance_id,
            is_pod_request_triggered,
            triggered_at,
            created_at,
            updated_at
        )
        SELECT DISTINCT ON (tenant_id, shipment_id)
            tenant_id,
            shipment_id,
            workflow_instance_id,
            TRUE,
            wr.created_at,
            wr.created_at,
            NOW()
        FROM workflow_runs wr
        WHERE wr.event_type = 'route_completed' AND shipment_id IS NOT NULL
        ORDER BY tenant_id, shipment_id, wr.created_at DESC
        ON CONFLICT (tenant_name, shipment_id) DO NOTHING;
        """
    )
    op.execute("DROP TABLE IF EXISTS workflow_runs CASCADE")
