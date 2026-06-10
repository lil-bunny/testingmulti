"""Rename pod_lifecycle sub-status upload_to_tms -> uploaded_to_tms.

Revision ID: 20260610_01
Revises: 20260609_04
Create Date: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260610_01"
down_revision: Union[str, Sequence[str], None] = "20260609_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'uploaded_to_tms'"
    )
    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'uploaded_to_tms'::lifecycle_sub_status,
            updated_at = NOW()
        WHERE sub_status = 'upload_to_tms'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET from_sub_status = 'uploaded_to_tms'::lifecycle_sub_status
        WHERE from_sub_status = 'upload_to_tms'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET to_sub_status = 'uploaded_to_tms'::lifecycle_sub_status
        WHERE to_sub_status = 'upload_to_tms'::lifecycle_sub_status
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'upload_to_tms'::lifecycle_sub_status,
            updated_at = NOW()
        WHERE sub_status = 'uploaded_to_tms'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET from_sub_status = 'upload_to_tms'::lifecycle_sub_status
        WHERE from_sub_status = 'uploaded_to_tms'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET to_sub_status = 'upload_to_tms'::lifecycle_sub_status
        WHERE to_sub_status = 'uploaded_to_tms'::lifecycle_sub_status
        """
    )
