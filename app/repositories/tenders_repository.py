"""Batch insert into ``tenders``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


@dataclass(frozen=True)
class TenderInsertResult:
    """``created`` is True when a new row was inserted; False when the order already existed."""

    tender_id: str
    created: bool


class TendersRepository:
    TABLE_NAME = "tenders"

    def insert_batch(self, rows: list[dict[str, Any]]) -> list[TenderInsertResult]:
        """
        Insert rows in order; return id + whether each row was newly created.

        Uses ``ON CONFLICT (tenant_id, order_number) DO NOTHING`` and resolves the
        existing id when the order was already stored for that tenant.
        """

        if not rows:
            return []

        conn = psycopg.connect(settings.DATABASE_URL)
        insert_sql = f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                order_number,
                customer_name,
                product_name,
                order_quantity,
                shipping_date,
                delivery_date,
                pickup_location_id,
                delivery_location_id,
                pack_code_id,
                load_type,
                data_import_id,
                delivery_address,
                metadata
            )
            VALUES (
                %s::uuid,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::load_type,
                %s::uuid,
                %s,
                %s
            )
            ON CONFLICT ON CONSTRAINT tenders_tenant_order_number_unique
            DO NOTHING
            RETURNING id
        """
        lookup_sql = f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = %s::uuid AND order_number = %s
            LIMIT 1
        """
        results: list[TenderInsertResult] = []
        try:
            with conn.cursor() as cur:
                for r in rows:
                    cur.execute(
                        insert_sql,
                        (
                            r["tenant_id"],
                            r["order_number"],
                            r["customer_name"],
                            r["product_name"],
                            r["order_quantity"],
                            r.get("shipping_date"),
                            r.get("delivery_date"),
                            r.get("pickup_location_id"),
                            r.get("delivery_location_id"),
                            r.get("pack_code_id"),
                            r["load_type"],
                            r["data_import_id"],
                            Json(r.get("delivery_address")),
                            Json(r.get("metadata") or {}),
                        ),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        results.append(
                            TenderInsertResult(tender_id=str(row[0]), created=True)
                        )
                        continue
                    cur.execute(
                        lookup_sql,
                        (r["tenant_id"], r["order_number"]),
                    )
                    existing = cur.fetchone()
                    if existing and existing[0]:
                        results.append(
                            TenderInsertResult(
                                tender_id=str(existing[0]),
                                created=False,
                            )
                        )
            conn.commit()
        finally:
            conn.close()

        return results
