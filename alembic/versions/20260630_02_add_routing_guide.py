"""Routing guide: lifecycle sub-status ladder and master lookup table and add `workflow_lifecycle_id` onto communications

Revision ID: 20260630_02
Revises: 20260630_01
Create Date: 2026-06-30

Appends six ``lifecycle_sub_status`` values for capped per-carrier display:
``tender_sent_to_tenant_for_carrier_{1..3}`` and ``tender_sent_to_carrier_{1..3}``.

Creates ``routing_guide`` for zip-first lane lookup (tenant + customer_name + zipcode).
``city`` / ``state``: lane location from seed CSV; not used in lookup.
``customer_aliases``: LIEFMATCH strings; ``carriers``: ``{a|b|c: {name, email}}``.

Routing attempt counter lives in ``tenders.metadata.ftl.routing_guide.attempt`` (JSONB;
no column change). Application guards must compare by value, not enum sort order.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260630_02"
down_revision: Union[str, Sequence[str], None] = "20260630_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SUB_STATUSES: tuple[str, ...] = (
    "tender_sent_to_tenant_for_carrier_1",
    "tender_sent_to_tenant_for_carrier_2",
    "tender_sent_to_tenant_for_carrier_3",
    "tender_sent_to_carrier_1",
    "tender_sent_to_carrier_2",
    "tender_sent_to_carrier_3",
)

# Enum shape at ``20260623_01`` head (downgrade target); excludes routing-guide ladder values.
_DOWNGRADE_ENUM_VALUES: tuple[str, ...] = (
    "none",
    "tender_created",
    "tender_sent_to_tenant",
    "tender_sent_to_carrier",
    "reminder_1_sent",
    "reminder_2_sent",
    "accepted",
    "rejected",
    "do_nothing",
    "escalated",
    "reminder_3_sent",
    "pod_started",
    "ratecon_started",
    "document_uploaded",
    "document_processed",
    "uploaded_to_tms",
    "resolved_manually",
    "driver_assignment_started",
    "reminder_4_sent",
    "driver_details_email_received",
    "details_received",
    "cancelled",
)


def _add_sub_status_values() -> None:
    with op.get_context().autocommit_block():
        for value in _NEW_SUB_STATUSES:
            op.execute(
                f"ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS '{value}'"
            )


def _remap_routing_guide_sub_status(column: str) -> str:
    return f"""
        CASE {column}::text
            WHEN 'tender_sent_to_tenant_for_carrier_1' THEN 'tender_sent_to_tenant'
            WHEN 'tender_sent_to_tenant_for_carrier_2' THEN 'tender_sent_to_tenant'
            WHEN 'tender_sent_to_tenant_for_carrier_3' THEN 'tender_sent_to_tenant'
            WHEN 'tender_sent_to_carrier_1' THEN 'tender_sent_to_carrier'
            WHEN 'tender_sent_to_carrier_2' THEN 'tender_sent_to_carrier'
            WHEN 'tender_sent_to_carrier_3' THEN 'tender_sent_to_carrier'
            ELSE {column}::text
        END
    """


def _swap_lifecycle_sub_status_enum(*, values: tuple[str, ...]) -> None:
    enum_literals = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"""
        CREATE TYPE lifecycle_sub_status_prev AS ENUM ({enum_literals})
        """
    )
    op.execute(
        f"""
        ALTER TABLE workflow_lifecycles
            ALTER COLUMN sub_status TYPE lifecycle_sub_status_prev
            USING {_remap_routing_guide_sub_status("sub_status")}::text::lifecycle_sub_status_prev
        """
    )
    op.execute(
        f"""
        ALTER TABLE activity_logs
            ALTER COLUMN from_sub_status TYPE lifecycle_sub_status_prev
            USING {_remap_routing_guide_sub_status("from_sub_status")}::text::lifecycle_sub_status_prev,
            ALTER COLUMN to_sub_status TYPE lifecycle_sub_status_prev
            USING {_remap_routing_guide_sub_status("to_sub_status")}::text::lifecycle_sub_status_prev
        """
    )
    op.execute("DROP TYPE lifecycle_sub_status")
    op.execute("ALTER TYPE lifecycle_sub_status_prev RENAME TO lifecycle_sub_status")


def _create_routing_guide_table() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS routing_guide (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            customer_name TEXT NOT NULL,
            zipcode TEXT NOT NULL,
            city TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            customer_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
            carriers JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT routing_guide_tenant_customer_zip_unique
                UNIQUE (tenant_id, customer_name, zipcode)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS routing_guide_tenant_zipcode_idx
            ON routing_guide (tenant_id, zipcode)
        """
    )


def _drop_routing_guide_table() -> None:
    op.execute("DROP INDEX IF EXISTS routing_guide_tenant_zipcode_idx")
    op.execute("DROP TABLE IF EXISTS routing_guide")


def upgrade() -> None:
    # add `workflow_lifecycle_id` in communications
    op.execute(
        """
        ALTER TABLE communications
        ADD COLUMN IF NOT EXISTS workflow_lifecycle_id UUID
            REFERENCES workflow_lifecycles(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_communications_tenant_lifecycle_thread
        ON communications (tenant_id, workflow_lifecycle_id, thread_id)
        WHERE workflow_lifecycle_id IS NOT NULL
        """
    )
    # routing guide table
    _add_sub_status_values()
    _create_routing_guide_table()


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_communications_tenant_lifecycle_thread")
    op.execute(
        "ALTER TABLE communications DROP COLUMN IF EXISTS workflow_lifecycle_id"
    )
    _drop_routing_guide_table()
    _swap_lifecycle_sub_status_enum(values=_DOWNGRADE_ENUM_VALUES)
