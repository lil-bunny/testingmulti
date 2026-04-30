"""Drop workflow_runs.load_id / reminder_step; normalize reminder rows.

Reminder rows use event_type reminder_<step> instead of reminder_due + column.

Revision ID: 20260501_01
Revises: 20260431
Create Date: 2026-05-01
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260501_01"
down_revision: Union[str, Sequence[str], None] = "20260431"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE workflow_runs
        SET event_type = 'reminder_' || reminder_step::text
        WHERE event_type = 'reminder_due' AND reminder_step IS NOT NULL;
        DELETE FROM workflow_runs
        WHERE event_type = 'reminder_due';
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_wi_reminder_step")
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_tenant_load_route_completed")
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_wi_entry_event")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS load_id")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS reminder_step")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_workflow_runs_wi_entry_event ON workflow_runs (workflow_instance_id, event_type)
        WHERE event_type <> 'process_pod_followup';
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_wi_entry_event")
    op.execute(
        """
        ALTER TABLE workflow_runs
            ADD COLUMN IF NOT EXISTS load_id TEXT,
            ADD COLUMN IF NOT EXISTS reminder_step SMALLINT;
        """
    )
    op.execute(
        """
        UPDATE workflow_runs
        SET
            reminder_step = substring(event_type FROM 'reminder_(\\d+)')::smallint,
            event_type = 'reminder_due'
        WHERE event_type ~ '^reminder_\\d+$';
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_wi_entry_event ON workflow_runs (workflow_instance_id, event_type)
        WHERE event_type NOT IN ('process_pod_followup', 'reminder_due');
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_wi_reminder_step ON workflow_runs (workflow_instance_id, reminder_step)
        WHERE event_type = 'reminder_due';
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_tenant_load_route_completed ON workflow_runs (tenant_id, load_id)
        WHERE event_type = 'route_completed' AND shipment_id IS NULL AND load_id IS NOT NULL;
        """
    )
