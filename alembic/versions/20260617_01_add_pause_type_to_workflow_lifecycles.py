"""Add ``pause_type`` to workflow lifecycles and ``exception`` activity log type.

Revision ID: 20260617_01
Revises: 20260525_01
Create Date: 2026-06-17

- ``lifecycle_pause_type`` on ``workflow_lifecycles`` — why a lifecycle is paused
  (system error vs. business exception) for review-queue routing.
- ``exception`` value on ``activity_log_type`` — snapshot row for catalog failures
  (same lifecycle semantics as ``action``).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260617_01"
down_revision: Union[str, Sequence[str], None] = "20260525_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE activity_log_type ADD VALUE IF NOT EXISTS 'exception'")
    op.execute(
        """
        ALTER TABLE activity_logs
        DROP CONSTRAINT IF EXISTS activity_logs_action_snapshot_chk
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
        ADD CONSTRAINT activity_logs_action_snapshot_chk CHECK (
            activity_type NOT IN ('action', 'exception')
            OR (
                from_status = to_status
                AND from_sub_status = to_sub_status
            )
        )
        """
    )
    op.execute(
        """
        CREATE TYPE lifecycle_pause_type AS ENUM (
            'system_error',
            'business_exception'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
        ADD COLUMN IF NOT EXISTS pause_type lifecycle_pause_type
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS pause_type")
    op.execute("DROP TYPE IF EXISTS lifecycle_pause_type")
    op.execute(
        """
        ALTER TABLE activity_logs
        DROP CONSTRAINT IF EXISTS activity_logs_action_snapshot_chk
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
        ADD CONSTRAINT activity_logs_action_snapshot_chk CHECK (
            activity_type <> 'action'
            OR (
                from_status = to_status
                AND from_sub_status = to_sub_status
            )
        )
        """
    )
