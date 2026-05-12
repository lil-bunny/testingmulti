"""Drop unique constraints from workflow_runs — table is now a pure execution log.

Each graph invocation inserts a row keyed by execution_id (PK).  The old
partial-unique indexes enforced dedup-by-insert which is replaced by read-based
checks in WorkflowRunsService.workflow_initial_path_blocked.

Revision ID: 20260509_01
Revises: 20260508_01
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260509_01"
down_revision: Union[str, Sequence[str], None] = "20260508_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_wl_entry_event")
    op.execute("DROP INDEX IF EXISTS uq_workflow_runs_tenant_shipment_route_completed")


def downgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_wl_entry_event
        ON workflow_runs (workflow_lifecycle_id, event_type)
        WHERE event_type <> 'process_pod_followup';
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_runs_tenant_shipment_route_completed
        ON workflow_runs (tenant_id, shipment_id)
        WHERE event_type = 'route_completed' AND shipment_id IS NOT NULL;
        """
    )
