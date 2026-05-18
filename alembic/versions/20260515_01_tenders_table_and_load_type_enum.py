"""tenders table and load_type_enum

Revision ID: 20260515_01
Revises: 20260514_01
Create Date: 2026-05-15
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260515_01"
down_revision: Union[str, Sequence[str], None] = "20260514_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE load_type_enum AS ENUM (
                'ltl',
                'ftl',
                'partial',
                'container',
                'air',
                'ocean',
                'other'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              uuid NOT NULL REFERENCES tenants(id),

            order_number           text NOT NULL,
            customer_name          text NOT NULL,
            product_name           text NOT NULL,
            order_quantity         numeric NOT NULL,

            shipping_date          date,
            delivery_date          date,

            pickup_location_id     uuid,
            delivery_location_id   uuid,
            pack_code_id           uuid,

            status                 text NOT NULL DEFAULT 'po_imported',
            load_type              load_type_enum,

            data_import_id         uuid REFERENCES data_imports(id),

            metadata               jsonb NOT NULL DEFAULT '{}'::jsonb,

            created_at             timestamptz DEFAULT now(),
            updated_at             timestamptz DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenders")
    op.execute("DROP TYPE IF EXISTS load_type_enum")
