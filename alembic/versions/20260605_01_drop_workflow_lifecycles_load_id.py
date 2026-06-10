"""Drop ``workflow_lifecycles.load_id`` (correlation uses shipment FK + thread/tender).

Revision ID: 20260605_01
Revises: 20260603_02
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_01"
down_revision: Union[str, Sequence[str], None] = "20260603_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE workflow_lifecycles wl
        SET shipment_id = s.id,
            updated_at = NOW()
        FROM shipments s
        WHERE wl.shipment_id IS NULL
          AND wl.load_id IS NOT NULL
          AND wl.load_id = s.metadata->>'load_id'
          AND wl.tenant_id = s.tenant_id
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_load_id")
    op.execute("ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS load_id")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            ADD COLUMN IF NOT EXISTS load_id TEXT
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_load_id
        ON workflow_lifecycles (load_id)
        """
    )
