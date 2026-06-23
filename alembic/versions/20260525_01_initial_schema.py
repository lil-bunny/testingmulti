"""FreightX application schema (DDL only).

Revision ID: 20260525_01
Create Date: 2026-06-11

FreightX workflow / logistics tables. Requires ``tenants`` from
``20260521_01_identity_rbac`` (run that revision first).

Excludes LangGraph checkpoint tables and legacy portal tables
(documents1, turvo_user_oauth, user_roles).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260525_01"
down_revision: Union[str, Sequence[str], None] = None # requires revision 20260521_01_identity_rbac, but leaving as None to avoid circular dependency in tests
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TYPE load_type AS ENUM ('FTL', 'LTL')
        """
    )
    op.execute(
        """
        CREATE TYPE lifecycle_status AS ENUM (
            'processing',
            'completed',
            'failed',
            'pending_review',
            'none'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE lifecycle_sub_status AS ENUM (
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
            'reminder_4_sent',
            'driver_assignment_started',
            'driver_details_email_received',
            'details_received',
            'cancelled',
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
        CREATE TYPE activity_log_type AS ENUM (
            'action',
            'status_change',
            'sub_status_change'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE actor_type AS ENUM ('system', 'user')
        """
    )
    op.execute(
        """
        CREATE TYPE workflow_run_event_type AS ENUM (
            'route_completed',
            'email_received',
            'reminder_due',
            'tender_created',
            'carrier_email_received',
            'ack_received',
            'escalation_due',
            'manual_pod_upload',
            'ratecon_completed',
            'driver_details_email_received'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE document_type AS ENUM (
            'pod',
            'ratecon'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE document_analysis_type AS ENUM (
            'ratecon_extraction',
            'pod_extraction',
            'pod_vs_ratecon_comparison'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE communication_channel AS ENUM (
            'email', 'slack', 'teams'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE communication_direction AS ENUM (
            'inbound', 'outbound'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE data_import_source_type AS ENUM ('email', 'api')
        """
    )
    op.execute(
        """
        CREATE TYPE data_import_data_type AS ENUM (
            'load_tender',
            'delivery_location'
        )
        """
    )
    op.execute(
        """
        CREATE TYPE weight_unit AS ENUM ('kg', 'lbs')
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS locations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            city TEXT,
            state TEXT,
            state_code TEXT,
            postal_code TEXT,
            country TEXT NOT NULL DEFAULT 'US',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

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
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT pack_codes_tenant_id_pack_code_key UNIQUE (tenant_id, pack_code)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_imports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            data_type data_import_data_type NOT NULL,
            source_type data_import_source_type NOT NULL,
            file_name TEXT,
            raw_data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS shipments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            shipment_number TEXT NOT NULL,
            pickup_location_id UUID REFERENCES locations(id),
            delivery_location_id UUID REFERENCES locations(id),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            delivery_address JSONB,
            delivery_date DATE,
            carrier_name TEXT,
            customer_name TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT shipments_tenant_shipment_number_unique
                UNIQUE (tenant_id, shipment_number)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id UUID PRIMARY KEY,
            type document_type NOT NULL,
            shipment_id UUID,
            storage_key TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_documents_shipment_id
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL,
            CONSTRAINT uq_documents_storage_key UNIQUE (storage_key)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_one_pod_per_shipment
            ON documents (shipment_id)
            WHERE type = 'pod'::document_type AND shipment_id IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_analysis (
            id UUID PRIMARY KEY,
            shipment_id UUID,
            analysis_type document_analysis_type NOT NULL,
            confidence_score DOUBLE PRECISION,
            llm_model JSONB,
            results JSONB,
            document_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_document_analysis_shipment_id
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL,
            CONSTRAINT fk_document_analysis_document_id
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
            CONSTRAINT document_analysis_shipment_id_analysis_type_key
                UNIQUE (shipment_id, analysis_type)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenders (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            order_number TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            shipping_date DATE,
            delivery_date DATE,
            pickup_location_id UUID REFERENCES locations(id),
            delivery_location_id UUID REFERENCES locations(id),
            load_type load_type,
            data_import_id UUID REFERENCES data_imports(id),
            delivery_address JSONB,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT tenders_tenant_order_number_unique UNIQUE (tenant_id, order_number)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tender_products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            tender_id UUID NOT NULL
                REFERENCES tenders(id) ON DELETE CASCADE,
            pack_code_id UUID REFERENCES pack_codes(id),
            product_name TEXT NOT NULL,
            order_quantity NUMERIC NOT NULL,
            price_per_unit NUMERIC,
            weight_unit weight_unit NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_lifecycles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            workflow_name TEXT,
            shipment_id UUID REFERENCES shipments(id),
            tender_id UUID REFERENCES tenders(id) ON DELETE SET NULL,
            status lifecycle_status,
            sub_status lifecycle_sub_status,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            workflow_lifecycle_id UUID NOT NULL
                REFERENCES workflow_lifecycles(id) ON DELETE CASCADE,
            event_type workflow_run_event_type,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS communications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            channel communication_channel NOT NULL,
            direction communication_direction NOT NULL,
            external_id TEXT,
            thread_id TEXT,
            content TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            workflow_run_id UUID
                REFERENCES workflow_runs(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL
                REFERENCES tenants(id) ON DELETE CASCADE,
            workflow_lifecycle_id UUID NOT NULL
                REFERENCES workflow_lifecycles(id) ON DELETE CASCADE,
            workflow_run_id UUID
                REFERENCES workflow_runs(id) ON DELETE CASCADE,
            activity_type activity_log_type NOT NULL,
            description TEXT,
            from_status lifecycle_status NOT NULL,
            to_status lifecycle_status NOT NULL,
            from_sub_status lifecycle_sub_status NOT NULL,
            to_sub_status lifecycle_sub_status NOT NULL,
            actor_type actor_type NOT NULL,
            actor_id UUID NOT NULL,
            metadata JSONB DEFAULT '{}'::jsonb,
            communication_id UUID
                REFERENCES communications(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT activity_logs_action_snapshot_chk CHECK (
                activity_type <> 'action'
                OR (
                    from_status = to_status
                    AND from_sub_status = to_sub_status
                )
            )
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pack_codes_tenant_id ON pack_codes (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_analysis_shipment_id "
        "ON document_analysis (shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_analysis_analysis_type "
        "ON document_analysis (analysis_type)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_document_analysis_document_id
        ON document_analysis (document_id)
        WHERE document_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_shipment_id_type
        ON documents (shipment_id, type)
        WHERE shipment_id IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_shipments_tenant_id ON shipments (tenant_id)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS locations_city_state_postal_country_key
        ON locations (city, state_code, postal_code, country)
        WHERE city IS NOT NULL AND state_code IS NOT NULL
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenders_tenant_id ON tenders (tenant_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tender_products_tenant_id "
        "ON tender_products (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tender_products_tender_id "
        "ON tender_products (tender_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tender_products_pack_code_id "
        "ON tender_products (pack_code_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tenant_id "
        "ON workflow_lifecycles (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_shipment_id "
        "ON workflow_lifecycles (shipment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_lifecycles_tender_id "
        "ON workflow_lifecycles (tender_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_lifecycle_id "
        "ON workflow_runs (workflow_lifecycle_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_created_at "
        "ON workflow_runs (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_logs_lifecycle_id "
        "ON activity_logs (workflow_lifecycle_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_activity_logs_run_id "
        "ON activity_logs (workflow_run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_communications_tenant_id "
        "ON communications (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_communications_thread_id "
        "ON communications (thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_communications_workflow_run_id "
        "ON communications (workflow_run_id) "
        "WHERE workflow_run_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_communications_tenant_thread_run
        ON communications (tenant_id, thread_id)
        WHERE workflow_run_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_communications_tenant_external_id
        ON communications (tenant_id, external_id)
        WHERE external_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenants_settings_inbound_routing_emails_gin
        ON tenants
        USING GIN ((settings->'inbound_routing_emails'))
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_tenants_settings_inbound_routing_emails_gin"
    )
    op.execute("DROP TABLE IF EXISTS activity_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS communications CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS workflow_lifecycles CASCADE")
    op.execute("DROP TABLE IF EXISTS tender_products CASCADE")
    op.execute("DROP TABLE IF EXISTS tenders CASCADE")
    op.execute("DROP TABLE IF EXISTS document_analysis CASCADE")
    op.execute("DROP TABLE IF EXISTS documents CASCADE")
    op.execute("DROP TABLE IF EXISTS shipments CASCADE")
    op.execute("DROP TABLE IF EXISTS data_imports CASCADE")
    op.execute("DROP TABLE IF EXISTS pack_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS locations CASCADE")

    op.execute("DROP TYPE IF EXISTS weight_unit")
    op.execute("DROP TYPE IF EXISTS communication_direction")
    op.execute("DROP TYPE IF EXISTS communication_channel")
    op.execute("DROP TYPE IF EXISTS data_import_data_type")
    op.execute("DROP TYPE IF EXISTS data_import_source_type")
    op.execute("DROP TYPE IF EXISTS document_analysis_type")
    op.execute("DROP TYPE IF EXISTS document_type")
    op.execute("DROP TYPE IF EXISTS workflow_run_event_type")
    op.execute("DROP TYPE IF EXISTS actor_type")
    op.execute("DROP TYPE IF EXISTS activity_log_type")
    op.execute("DROP TYPE IF EXISTS lifecycle_sub_status")
    op.execute("DROP TYPE IF EXISTS lifecycle_status")
    op.execute("DROP TYPE IF EXISTS load_type")

    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
