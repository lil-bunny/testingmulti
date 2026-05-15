"""Batch insert into ``tenders``."""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings


class TendersRepository:
    TABLE_NAME = "tenders"

    def insert_batch(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0

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
                status,
                load_type,
                data_import_id
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
                %s,
                %s::load_type_enum,
                %s::uuid
            )
        """
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
                            r["status"],
                            r["load_type"],
                            r["data_import_id"],
                        ),
                    )
            conn.commit()
        finally:
            conn.close()

        return len(rows)
