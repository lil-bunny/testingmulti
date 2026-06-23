"""Add ``resolved_manually`` to ``lifecycle_sub_status``.

Revision ID: 20260622_01
Revises: 20260618_01
Create Date: 2026-06-22
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260622_01"
down_revision: Union[str, Sequence[str], None] = "20260618_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE lifecycle_sub_status "
            "ADD VALUE IF NOT EXISTS 'resolved_manually'"
        )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value. Recreate the type only if no
    # rows reference 'resolved_manually' (otherwise downgrade will fail).
    op.execute(
        """
        CREATE TYPE lifecycle_sub_status_prev AS ENUM (
            'none',
            'tender_created',
            'tender_sent_to_tenant',
            'tender_sent_to_carrier',
            'reminder_1_sent',
            'reminder_2_sent',
            'accepted',
            'rejected',
            'do_nothing',
            'escalated',
            'reminder_3_sent',
            'pod_started',
            'ratecon_started',
            'document_uploaded',
            'document_processed',
            'uploaded_to_tms'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
            ALTER COLUMN sub_status TYPE lifecycle_sub_status_prev
            USING sub_status::text::lifecycle_sub_status_prev
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN from_sub_status TYPE lifecycle_sub_status_prev
            USING from_sub_status::text::lifecycle_sub_status_prev,
            ALTER COLUMN to_sub_status TYPE lifecycle_sub_status_prev
            USING to_sub_status::text::lifecycle_sub_status_prev
        """
    )
    op.execute("DROP TYPE lifecycle_sub_status")
    op.execute(
        "ALTER TYPE lifecycle_sub_status_prev RENAME TO lifecycle_sub_status"
    )
