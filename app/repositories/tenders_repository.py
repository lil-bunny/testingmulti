"""Reads and batch insert for ``tenders``."""

from __future__ import annotations

import json
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

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        return json.loads(value)

    def get_by_id(
        self, *, tenant_id: str, tender_id: str
    ) -> dict[str, Any] | None:
        """Order-level tender row (no product lines)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        if not tid or not tr:
            return None

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        id::text,
                        order_number,
                        load_type::text,
                        customer_name,
                        shipping_date,
                        delivery_date,
                        pickup_location_id::text,
                        delivery_location_id::text,
                        delivery_address,
                        metadata
                    FROM {self.TABLE_NAME}
                    WHERE id = %s::uuid AND tenant_id = %s::uuid
                    LIMIT 1
                    """,
                    (tr, tid),
                )
                row = cur.fetchone()
                if not row:
                    return None

                delivery_raw = row[8]
                if isinstance(delivery_raw, dict):
                    delivery_address = delivery_raw
                elif delivery_raw in (None, ""):
                    delivery_address = None
                else:
                    delivery_address = json.loads(delivery_raw)

                return {
                    "id": str(row[0]),
                    "order_number": row[1] or "",
                    "load_type": row[2] or "",
                    "customer_name": row[3] or "",
                    "shipping_date": row[4],
                    "delivery_date": row[5],
                    "pickup_location_id": row[6],
                    "delivery_location_id": row[7],
                    "delivery_address": delivery_address,
                    "metadata": self._parse_json(row[9]),
                }
        finally:
            conn.close()

    def get_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        """Return ``{id, order_number}`` for a tenant-scoped tender row, or ``None``."""
        tid = self._clean(tenant_id)
        order = self._clean(order_number)
        if not tid or not order:
            return None

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id::text, order_number
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid AND order_number = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (tid, order),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {"id": str(row[0]), "order_number": row[1] or ""}
        finally:
            conn.close()

    def update_load_type(
        self, *, tenant_id: str, tender_id: str, load_type: str
    ) -> bool:
        """Persist ``load_type`` on the tender (``LTL`` / ``FTL`` enum labels)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        lt = str(load_type or "").strip().upper()
        if not tid or not tr or lt not in {"LTL", "FTL"}:
            return False

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET load_type = %s::load_type, updated_at = NOW()
                    WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (lt, tr, tid),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()

    def insert_batch(self, rows: list[dict[str, Any]]) -> list[TenderInsertResult]:
        """
        Insert rows in order; return id + whether each row was newly created.

        On duplicate ``(tenant_id, order_number)``, does nothing (existing row unchanged).
        """

        if not rows:
            return []

        conn = psycopg.connect(settings.DATABASE_URL)
        insert_sql = f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                order_number,
                customer_name,
                shipping_date,
                delivery_date,
                pickup_location_id,
                delivery_location_id,
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
                %s::load_type,
                %s::uuid,
                %s,
                %s
            )
            ON CONFLICT ON CONSTRAINT tenders_tenant_order_number_unique
            DO NOTHING
            RETURNING id, (xmax = 0) AS inserted
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
                            r.get("shipping_date"),
                            r.get("delivery_date"),
                            r.get("pickup_location_id"),
                            r.get("delivery_location_id"),
                            r["load_type"],
                            r["data_import_id"],
                            Json(r.get("delivery_address")),
                            Json(r.get("metadata") or {}),
                        ),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        results.append(
                            TenderInsertResult(
                                tender_id=str(row[0]),
                                created=bool(row[1]),
                            )
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
