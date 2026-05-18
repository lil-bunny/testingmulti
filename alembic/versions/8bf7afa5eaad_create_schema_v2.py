"""create schema v2 uuid-only

Revision ID: 8bf7afa5eaad
Revises: 20260509_01
Create Date: 2026-05-15

Full UUID-based schema.
All primary keys and foreign keys use UUID.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "8bf7afa5eaad"
down_revision: Union[str, Sequence[str], None] = "20260509_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================
    # EXTENSIONS
    # =========================================================
    op.execute(
        """
        CREATE EXTENSION IF NOT EXISTS pgcrypto
        """
    )

    # =========================================================
    # CLEAN LEGACY TABLES (TEXT-ID TABLES)
    # =========================================================
    # Remove old incompatible tables if they exist.
    # Safe for staging/dev reset migrations.
    op.execute("DROP TABLE IF EXISTS activity_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_lifecycles CASCADE")

    # =========================================================
    # ENUMS
    # =========================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_type
                WHERE typname = 'load_type_enum'
            ) THEN
                CREATE TYPE load_type_enum AS ENUM (
                    'FTL',
                    'LTL',
                    'PARTIAL'
                );
            END IF;
        END$$;
        """
    )

    # =========================================================
    # USERS
    # =========================================================
    # op.execute(
    #     """
    #     CREATE TABLE IF NOT EXISTS users (
    #         id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    #         email TEXT NOT NULL UNIQUE,
    #         name TEXT,
    #         password_hash TEXT NOT NULL,
    #         created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    #         updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    #     )
    #     """
    # )


    # =========================================================
    # TENANTS
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # LOCATIONS
    # =========================================================
    # op.execute(
    #     """
    #     CREATE TABLE IF NOT EXISTS locations (
    #         id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    #         city TEXT,
    #         state TEXT,
    #         state_code TEXT,
    #         created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    #         updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    #     )
    #     """
    # )

    # =========================================================
    # ORGANIZATIONS
    # =========================================================
    # op.execute(
    #     """
    #     CREATE TABLE IF NOT EXISTS organizations (
    #         id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    #         name TEXT NOT NULL,
    #         created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    #     )
    #     """
    # )

    # =========================================================
    # DATA IMPORTS
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_imports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # USER ROLES
    # =========================================================
    # op.execute(
    #     """
    #     CREATE TABLE IF NOT EXISTS user_roles (
    #         id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    #         user_id UUID NOT NULL
    #             REFERENCES users(id) ON DELETE CASCADE,

    #         role TEXT NOT NULL,

    #         created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    #         created_by UUID
    #             REFERENCES users(id)
    #     )
    #     """
    # )

    # =========================================================
    # PACK CODES
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pack_codes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            pack_code TEXT NOT NULL,
            description TEXT,
            units_per_pallet NUMERIC,
            qty_per_unit NUMERIC,
            total_qty NUMERIC,
            unit_dims TEXT,
            pallet_dims TEXT,
            pallet_type TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, pack_code)
        )
        """
    )

    # =========================================================
    # SHIPMENTS
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            shipper_organization_id UUID
                REFERENCES organizations(id),

            status TEXT,

            pickup_location_id UUID
                REFERENCES locations(id),

            delivery_location_id UUID
                REFERENCES locations(id),

            pack_code_id UUID
                REFERENCES pack_codes(id),

            notes TEXT,

            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # TENDERS
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            order_number TEXT NOT NULL,

            customer_name TEXT NOT NULL,

            product_name TEXT NOT NULL,

            order_quantity NUMERIC NOT NULL,

            shipping_date DATE,

            delivery_date DATE,

            pickup_location_id UUID
                REFERENCES locations(id),

            delivery_location_id UUID
                REFERENCES locations(id),

            pack_code TEXT NOT NULL,

            status TEXT NOT NULL DEFAULT 'processing',

            load_type load_type_enum,

            data_import_id UUID
                REFERENCES data_imports(id),

            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT tenders_tenant_pack_code_fkey
                FOREIGN KEY (tenant_id, pack_code)
                REFERENCES pack_codes (tenant_id, pack_code)
        )
        """
    )

    # =========================================================
    # WORKFLOW LIFECYCLES
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_lifecycles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            workflow_name TEXT,

            shipment_id UUID
                REFERENCES shipments(id),

            tender_id UUID
                REFERENCES tenders(id),

            status TEXT,

            sub_status TEXT,

            email_thread_id TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # WORKFLOW RUNS
    # =========================================================
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            workflow_lifecycle_id UUID NOT NULL
                REFERENCES workflow_lifecycles(id) ON DELETE CASCADE,

            event_type TEXT,

            status TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # ACTIVITY LOGS
    # =========================================================
    # ask team about this cascade
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,

            workflow_lifecycle_id UUID
                REFERENCES workflow_lifecycles(id) ON DELETE CASCADE,

            workflow_run_id UUID
                REFERENCES workflow_runs(id) ON DELETE CASCADE,

            activity_type TEXT,

            message TEXT,

            from_status TEXT,
            to_status TEXT,

            from_sub_status TEXT,
            to_sub_status TEXT,

            actor_type TEXT,

            actor_id UUID,

            payload JSONB NOT NULL DEFAULT '{}'::jsonb,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # =========================================================
    # INDEXES
    # =========================================================
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_roles_user_id
        ON user_roles(user_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pack_codes_tenant_id
        ON pack_codes(tenant_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shipments_tenant_id
        ON shipments(tenant_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_shipments_pack_code_id
        ON shipments(pack_code_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenders_tenant_id
        ON tenders(tenant_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenders_status
        ON tenders(status)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tenant_id
        ON workflow_lifecycles(tenant_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_shipment_id
        ON workflow_lifecycles(shipment_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tender_id
        ON workflow_lifecycles(tender_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_runs_lifecycle_id
        ON workflow_runs(workflow_lifecycle_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_logs_lifecycle_id
        ON activity_logs(workflow_lifecycle_id)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_activity_logs_run_id
        ON activity_logs(workflow_run_id)
        """
    )


def downgrade() -> None:
    # =========================================================
    # DROP INDEXES
    # =========================================================
    op.execute("DROP INDEX IF EXISTS idx_activity_logs_run_id")
    op.execute("DROP INDEX IF EXISTS idx_activity_logs_lifecycle_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_runs_lifecycle_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_tender_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_shipment_id")
    op.execute("DROP INDEX IF EXISTS idx_workflow_lifecycles_tenant_id")
    op.execute("DROP INDEX IF EXISTS idx_tenders_status")
    op.execute("DROP INDEX IF EXISTS idx_tenders_tenant_id")
    op.execute("DROP INDEX IF EXISTS idx_shipments_pack_code_id")
    op.execute("DROP INDEX IF EXISTS idx_shipments_tenant_id")
    op.execute("DROP INDEX IF EXISTS idx_pack_codes_tenant_id")
    op.execute("DROP INDEX IF EXISTS idx_user_roles_user_id")

    # =========================================================
    # DROP TABLES
    # =========================================================
    op.execute("DROP TABLE IF EXISTS activity_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_lifecycles CASCADE")
    op.execute("DROP TABLE IF EXISTS tenders CASCADE")
    op.execute("DROP TABLE IF EXISTS shipments CASCADE")
    op.execute("DROP TABLE IF EXISTS pack_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS user_roles CASCADE")
    op.execute("DROP TABLE IF EXISTS data_imports CASCADE")
    op.execute("DROP TABLE IF EXISTS organizations CASCADE")
    op.execute("DROP TABLE IF EXISTS locations CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")

    # =========================================================
    # DROP ENUMS
    # =========================================================
    op.execute(
        """
        DROP TYPE IF EXISTS load_type_enum
        """
    )