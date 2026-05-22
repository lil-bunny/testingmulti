"""``activity_logs`` status columns NOT NULL; ``action`` snapshot CHECK.

Revision ID: 20260523_01
Revises: 20260522_03
Create Date: 2026-05-23

Assumes no ``activity_logs`` rows with NULL status/sub_status (empty or app already
writing full snapshots). No data backfill in this revision.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260523_01"
down_revision: Union[str, Sequence[str], None] = "20260522_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN from_status SET NOT NULL,
            ALTER COLUMN to_status SET NOT NULL,
            ALTER COLUMN from_sub_status SET NOT NULL,
            ALTER COLUMN to_sub_status SET NOT NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'activity_logs_action_snapshot_chk'
            ) THEN
                ALTER TABLE activity_logs
                    ADD CONSTRAINT activity_logs_action_snapshot_chk
                    CHECK (
                        activity_type <> 'action'
                        OR (
                            from_status = to_status
                            AND from_sub_status = to_sub_status
                        )
                    );
            END IF;
        END $$;
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
        ALTER TABLE activity_logs
            ALTER COLUMN from_status DROP NOT NULL,
            ALTER COLUMN to_status DROP NOT NULL,
            ALTER COLUMN from_sub_status DROP NOT NULL,
            ALTER COLUMN to_sub_status DROP NOT NULL
        """
    )
