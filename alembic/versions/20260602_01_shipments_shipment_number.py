"""Align ``shipments``: ``shipment_number``, drop legacy columns and ``shipper_organization_id``.

Revision ID: 20260602_01
Revises: 20260525_01
Create Date: 2026-06-02

Merged with former ``20260603_04`` (drop ``shipper_organization_id``).
Idempotent DDL for environments that still have the initial shipments shape.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260602_01"
down_revision: Union[str, Sequence[str], None] = "20260525_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
            ADD COLUMN IF NOT EXISTS shipment_number TEXT
        """
    )
    op.execute(
        """
        UPDATE shipments
        SET shipment_number = id::text
        WHERE shipment_number IS NULL OR trim(shipment_number) = ''
        """
    )
    op.execute(
        """
        ALTER TABLE shipments
            ALTER COLUMN shipment_number SET NOT NULL
        """
    )
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS pack_code_id")
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS notes")
    op.execute(
        "ALTER TABLE shipments DROP COLUMN IF EXISTS shipper_organization_id"
    )
    op.execute("DROP INDEX IF EXISTS idx_shipments_pack_code_id")
    op.execute(
        """
        ALTER TABLE shipments
            DROP CONSTRAINT IF EXISTS shipments_tenant_shipment_number_unique
        """
    )
    op.execute(
        """
        ALTER TABLE shipments
            ADD CONSTRAINT shipments_tenant_shipment_number_unique
                UNIQUE (tenant_id, shipment_number)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE shipments
            DROP CONSTRAINT IF EXISTS shipments_tenant_shipment_number_unique
        """
    )
    op.execute("ALTER TABLE shipments DROP COLUMN IF EXISTS shipment_number")
    op.execute("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS status TEXT")
    op.execute(
        """
        ALTER TABLE shipments
            ADD COLUMN IF NOT EXISTS pack_code_id UUID REFERENCES pack_codes(id)
        """
    )
    op.execute("ALTER TABLE shipments ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute(
        """
        ALTER TABLE shipments
            ADD COLUMN IF NOT EXISTS shipper_organization_id UUID
                REFERENCES organizations(id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shipments_pack_code_id
            ON shipments (pack_code_id)
        """
    )
