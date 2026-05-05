"""create pod_requests table for initial POD email idempotency per shipment

Revision ID: 20260429_01
Revises: 20260427_02
Create Date: 2026-04-29
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260429_01"
down_revision: Union[str, Sequence[str], None] = "20260427_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pod_requests (
            shipment_id TEXT PRIMARY KEY,
            workflow_instance_id TEXT NOT NULL,
            is_pod_request_triggered BOOLEAN NOT NULL DEFAULT FALSE,
            triggered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pod_requests_updated_at ON pod_requests(updated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pod_requests")
