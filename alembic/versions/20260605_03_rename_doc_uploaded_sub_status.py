"""Rename ratecon sub-status doc_uploaded -> document_uploaded.

Revision ID: 20260605_03
Revises: 20260605_02
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260605_03"
down_revision: Union[str, Sequence[str], None] = "20260605_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS 'document_uploaded'"
    )
    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'document_uploaded'::lifecycle_sub_status,
            updated_at = NOW()
        WHERE sub_status = 'doc_uploaded'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET from_sub_status = 'document_uploaded'::lifecycle_sub_status
        WHERE from_sub_status = 'doc_uploaded'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET to_sub_status = 'document_uploaded'::lifecycle_sub_status
        WHERE to_sub_status = 'doc_uploaded'::lifecycle_sub_status
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'doc_uploaded'::lifecycle_sub_status,
            updated_at = NOW()
        WHERE sub_status = 'document_uploaded'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET from_sub_status = 'doc_uploaded'::lifecycle_sub_status
        WHERE from_sub_status = 'document_uploaded'::lifecycle_sub_status
        """
    )
    op.execute(
        """
        UPDATE activity_logs
        SET to_sub_status = 'doc_uploaded'::lifecycle_sub_status
        WHERE to_sub_status = 'document_uploaded'::lifecycle_sub_status
        """
    )
