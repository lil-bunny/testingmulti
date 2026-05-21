"""Drop ``workflow_runs.status``; rename Gelita lifecycle sub_status enum values.

Revision ID: 20260521_01
Revises: 20260519_02
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_01"
down_revision: Union[str, Sequence[str], None] = "20260519_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SUB_STATUSES = (
    "tender_sent_to_tenant",
    "tender_sent_to_carrier",
)


def _add_enum_value(enum_name: str, value: str) -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            ALTER TYPE {enum_name} ADD VALUE '{value}';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def upgrade() -> None:
    # Enum labels must be committed before use in UPDATE (PostgreSQL).
    with op.get_context().autocommit_block():
        for value in _NEW_SUB_STATUSES:
            _add_enum_value("lifecycle_sub_status", value)

    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'tender_sent_to_tenant'::lifecycle_sub_status
        WHERE sub_status::text = 'tender_sent';

        UPDATE workflow_lifecycles
        SET sub_status = 'tender_sent_to_carrier'::lifecycle_sub_status
        WHERE sub_status::text = 'awaiting_response';

        UPDATE activity_logs
        SET from_sub_status = 'tender_sent_to_tenant'::lifecycle_sub_status
        WHERE from_sub_status::text = 'tender_sent';

        UPDATE activity_logs
        SET to_sub_status = 'tender_sent_to_tenant'::lifecycle_sub_status
        WHERE to_sub_status::text = 'tender_sent';

        UPDATE activity_logs
        SET from_sub_status = 'tender_sent_to_carrier'::lifecycle_sub_status
        WHERE from_sub_status::text = 'awaiting_response';

        UPDATE activity_logs
        SET to_sub_status = 'tender_sent_to_carrier'::lifecycle_sub_status
        WHERE to_sub_status::text = 'awaiting_response';
        """
    )
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS status")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE workflow_runs
            ADD COLUMN IF NOT EXISTS status text;
        """
    )
    op.execute(
        """
        UPDATE workflow_lifecycles
        SET sub_status = 'tender_sent'::lifecycle_sub_status
        WHERE sub_status::text = 'tender_sent_to_tenant';

        UPDATE workflow_lifecycles
        SET sub_status = 'awaiting_response'::lifecycle_sub_status
        WHERE sub_status::text = 'tender_sent_to_carrier';

        UPDATE activity_logs
        SET from_sub_status = 'tender_sent'::lifecycle_sub_status
        WHERE from_sub_status::text = 'tender_sent_to_tenant';

        UPDATE activity_logs
        SET to_sub_status = 'tender_sent'::lifecycle_sub_status
        WHERE to_sub_status::text = 'tender_sent_to_tenant';

        UPDATE activity_logs
        SET from_sub_status = 'awaiting_response'::lifecycle_sub_status
        WHERE from_sub_status::text = 'tender_sent_to_carrier';

        UPDATE activity_logs
        SET to_sub_status = 'awaiting_response'::lifecycle_sub_status
        WHERE to_sub_status::text = 'tender_sent_to_carrier';
        """
    )
