"""Add ``info`` activity log type for snapshot rows without status change.

Revision ID: 20260630_01
Revises: 20260629_01
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op

revision = "20260630_01"
down_revision = "20260629_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires new enum values to be committed before use in CHECK.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_log_type ADD VALUE IF NOT EXISTS 'info'"
        )
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
            activity_type NOT IN ('action', 'exception', 'info')
            OR (
                from_status = to_status
                AND from_sub_status = to_sub_status
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE activity_logs
        DROP CONSTRAINT IF EXISTS activity_logs_action_snapshot_chk
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET activity_type = 'action'
        WHERE activity_type = 'info'
        """
    )
    op.execute(
        """
        CREATE TYPE activity_log_type_prev AS ENUM (
            'action',
            'status_change',
            'sub_status_change',
            'exception'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN activity_type TYPE activity_log_type_prev
            USING activity_type::text::activity_log_type_prev
        """
    )
    op.execute("DROP TYPE activity_log_type")
    op.execute("ALTER TYPE activity_log_type_prev RENAME TO activity_log_type")
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
