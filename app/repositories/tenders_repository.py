"""Reads and batch insert for ``tenders``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import jsonb_param, parse_json

_WHERE_TENANT_TENDER_PK = """
    WHERE id = CAST(:tender_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)
"""

_WHERE_TENANT_ORDER = """
    WHERE tenant_id = CAST(:tenant_id AS uuid) AND order_number = :order_number
"""


@dataclass(frozen=True)
class TenderInsertResult:
    """``created`` is True when a new row was inserted; False when the order already existed."""

    tender_id: str
    created: bool


class TendersRepository:
    TABLE_NAME = "tenders"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def get_by_id(
        self, *, tenant_id: str, tender_id: str
    ) -> dict[str, Any] | None:
        """Order-level tender row (no product lines)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        if not tid or not tr:
            return None

        row = self._session.execute(
            text(
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
                    metadata,
                    weight_unit::text
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_TENDER_PK}
                LIMIT 1
                """
            ),
            {"tender_id": tr, "tenant_id": tid},
        ).first()
        if not row:
            return None

        delivery_raw = row[8]
        if isinstance(delivery_raw, dict):
            delivery_address = delivery_raw
        elif delivery_raw in (None, ""):
            delivery_address = None
        else:
            delivery_address = parse_json(delivery_raw)
            if not delivery_address:
                delivery_address = None

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
            "metadata": parse_json(row[9]),
            "weight_unit": row[10] or "",
        }

    def get_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        """Return ``{id, order_number}`` for a tenant-scoped tender row, or ``None``."""
        tid = self._clean(tenant_id)
        order = self._clean(order_number)
        if not tid or not order:
            return None

        row = self._session.execute(
            text(
                f"""
                SELECT id::text, order_number
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_ORDER}
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tid, "order_number": order},
        ).first()
        if not row:
            return None
        return {"id": str(row[0]), "order_number": row[1] or ""}

    def update_load_type(
        self, *, tenant_id: str, tender_id: str, load_type: str
    ) -> bool:
        """Persist ``load_type`` on the tender (``LTL`` / ``FTL`` enum labels)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        lt = str(load_type or "").strip().upper()
        if not tid or not tr or lt not in {"LTL", "FTL"}:
            return False

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET load_type = CAST(:load_type AS load_type), updated_at = NOW()
                {_WHERE_TENANT_TENDER_PK}
                """
            ),
            {"load_type": lt, "tender_id": tr, "tenant_id": tid},
        )
        return result.rowcount > 0

    def insert_batch(self, rows: list[dict[str, Any]]) -> list[TenderInsertResult]:
        """
        Insert rows in order; return id + whether each row was newly created.

        On duplicate ``(tenant_id, order_number)``, does nothing (existing row unchanged).
        """
        if not rows:
            return []

        insert_sql = text(
            f"""
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
                metadata,
                weight_unit
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                :order_number,
                :customer_name,
                :shipping_date,
                :delivery_date,
                CAST(:pickup_location_id AS uuid),
                CAST(:delivery_location_id AS uuid),
                CAST(:load_type AS load_type),
                CAST(:data_import_id AS uuid),
                CAST(:delivery_address AS jsonb),
                CAST(:metadata AS jsonb),
                CAST(:weight_unit AS weight_unit)
            )
            ON CONFLICT ON CONSTRAINT tenders_tenant_order_number_unique
            DO NOTHING
            RETURNING id, (xmax = 0) AS inserted
            """
        )
        lookup_sql = text(
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            {_WHERE_TENANT_ORDER}
            LIMIT 1
            """
        )
        results: list[TenderInsertResult] = []
        for r in rows:
            row = self._session.execute(
                insert_sql,
                {
                    "tenant_id": r["tenant_id"],
                    "order_number": r["order_number"],
                    "customer_name": r["customer_name"],
                    "shipping_date": r.get("shipping_date"),
                    "delivery_date": r.get("delivery_date"),
                    "pickup_location_id": r.get("pickup_location_id"),
                    "delivery_location_id": r.get("delivery_location_id"),
                    "load_type": r["load_type"],
                    "data_import_id": r["data_import_id"],
                    "delivery_address": jsonb_param(r.get("delivery_address")),
                    "metadata": jsonb_param(r.get("metadata") or {}),
                    "weight_unit": r.get("weight_unit"),
                },
            ).first()
            if row and row[0]:
                results.append(
                    TenderInsertResult(
                        tender_id=str(row[0]),
                        created=bool(row[1]),
                    )
                )
                continue
            existing = self._session.execute(
                lookup_sql,
                {
                    "tenant_id": r["tenant_id"],
                    "order_number": r["order_number"],
                },
            ).first()
            if existing and existing[0]:
                results.append(
                    TenderInsertResult(
                        tender_id=str(existing[0]),
                        created=False,
                    )
                )

        return results
