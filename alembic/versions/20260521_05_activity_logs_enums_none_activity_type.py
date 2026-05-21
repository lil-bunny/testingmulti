"""Add ``none`` to lifecycle enums; canonicalize sub_status data; enum ``activity_type``.

Revision ID: 20260521_05
Revises: 20260521_04
Create Date: 2026-05-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260521_05"
down_revision: Union[str, Sequence[str], None] = "20260521_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    with op.get_context().autocommit_block():
        _add_enum_value("lifecycle_status", "none")
        _add_enum_value("lifecycle_sub_status", "none")

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

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'activity_log_type'
            ) THEN
                CREATE TYPE activity_log_type AS ENUM (
                    'action',
                    'status_change',
                    'sub_status_change'
                );
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'activity_logs'
                  AND column_name = 'activity_type'
                  AND udt_name = 'text'
            ) THEN
                ALTER TABLE activity_logs
                    ALTER COLUMN activity_type TYPE activity_log_type
                    USING activity_type::activity_log_type;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'activity_logs'
                  AND column_name = 'activity_type'
                  AND udt_name = 'activity_log_type'
            ) THEN
                ALTER TABLE activity_logs
                    ALTER COLUMN activity_type TYPE text
                    USING activity_type::text;
            END IF;
        END $$;
        """
    )
    op.execute("DROP TYPE IF EXISTS activity_log_type")
