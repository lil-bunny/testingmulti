"""Add ratecon_completed to workflow_run_event_type enum."""

from __future__ import annotations

from alembic import op

revision = "20260616_01"
down_revision = "20260525_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE workflow_run_event_type ADD VALUE IF NOT EXISTS 'ratecon_completed'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
