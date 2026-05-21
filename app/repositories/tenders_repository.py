"""Batch insert into ``tenders``."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


class TendersRepository:
    TABLE_NAME = "tenders"

    def insert_batch(self, rows: list[dict[str, Any]]) -> list[str]:
        """Insert rows in order; return ``tenders.id`` for each inserted row."""

        if not rows:
            return []

        conn = psycopg.connect(settings.DATABASE_URL)
        sql = f"""
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
                %s::load_type_enum,
                %s::uuid,
                %s,
                %s
            )
            RETURNING id
        """
        inserted_ids: list[str] = []
        try:
            with conn.cursor() as cur:
                for r in rows:
                    cur.execute(
                        sql,
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
                        inserted_ids.append(str(row[0]))
            conn.commit()
        finally:
            conn.close()

        return inserted_ids
