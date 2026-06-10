"""documents + document_analysis shipment_id → nullable UUID FK.

Revision ID: 20260609_02
Revises: 20260609_01
Create Date: 2026-06-09

Aligns document tables with workflow_lifecycles.shipment_id (shipments.id UUID).
Legacy TEXT values holding Turvo shipment_number are backfilled before type change.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260609_02"
down_revision: Union[str, Sequence[str], None] = "20260609_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _migrate_table_shipment_id_to_uuid(*, table: str, unique_constraint: str | None) -> None:
    if unique_constraint:
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {unique_constraint}"
        )

    op.execute(
        f"""
        UPDATE {table} d
        SET shipment_id = s.id::text
        FROM shipments s
        WHERE d.shipment_id IS NOT NULL
          AND d.shipment_id = s.shipment_number
        """
    )
    op.execute(
        f"""
        UPDATE {table}
        SET shipment_id = NULL
        WHERE shipment_id IS NOT NULL
          AND shipment_id !~ '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$'
        """
    )
    op.execute(
        f"""
        ALTER TABLE {table}
        ALTER COLUMN shipment_id TYPE UUID USING shipment_id::uuid,
        ALTER COLUMN shipment_id DROP NOT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE {table}
        ADD CONSTRAINT fk_{table}_shipment_id
        FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
        """
    )

    if unique_constraint:
        op.execute(
            f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {unique_constraint}
            UNIQUE (shipment_id, analysis_type)
            """
        )


def upgrade() -> None:
    _migrate_table_shipment_id_to_uuid(
        table="documents",
        unique_constraint=None,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_documents_shipment_id_type
        ON documents (shipment_id, type)
        WHERE shipment_id IS NOT NULL
        """
    )

    _migrate_table_shipment_id_to_uuid(
        table="document_analysis",
        unique_constraint="document_analysis_shipment_id_analysis_type_key",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_documents_shipment_id_type")

    for table, unique_constraint in (
        ("document_analysis", "document_analysis_shipment_id_analysis_type_key"),
        ("documents", None),
    ):
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{table}_shipment_id"
        )
        if unique_constraint:
            op.execute(
                f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {unique_constraint}"
            )
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN shipment_id TYPE TEXT USING shipment_id::text,
            ALTER COLUMN shipment_id SET NOT NULL
            """
        )
        if unique_constraint:
            op.execute(
                f"""
                ALTER TABLE {table}
                ADD CONSTRAINT {unique_constraint}
                UNIQUE (shipment_id, analysis_type)
                """
            )
