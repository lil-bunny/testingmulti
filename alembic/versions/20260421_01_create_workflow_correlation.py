"""create workflow correlation table

Revision ID: 20260421_01
Revises:
Create Date: 2026-04-21 00:00:00
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260421_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS workflow_correlation;

        CREATE TABLE IF NOT EXISTS workflow_correlation (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            workflow_instance_id TEXT NOT NULL UNIQUE,
            shipment_id TEXT,
            load_id TEXT,
            email_thread_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
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
    op.execute("DROP TABLE IF EXISTS workflow_correlation")
