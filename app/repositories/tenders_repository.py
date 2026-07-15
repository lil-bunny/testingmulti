"""Reads and batch insert for ``tenders``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from sqlalchemy import text

from app.core.db import jsonb_param, parse_json

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_WHERE_TENANT_TENDER_PK = """
    WHERE id = CAST(:tender_id AS uuid) AND tenant_id = CAST(:tenant_id AS uuid)
"""

_WHERE_TENANT_ORDER = """
    WHERE tenant_id = CAST(:tenant_id AS uuid) AND order_number = :order_number
"""


@dataclass(frozen=True)
class TenderInsertResult:
    """``insert_batch`` outcome: new tender id and whether ingest should enqueue workflow."""

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
                    carrier_name
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
            "carrier_name": row[10] or None,
        }

    def get_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        """Latest ``{id, order_number, load_type}`` for ``(tenant_id, order_number)`` (``created_at DESC``), or ``None``."""
        tid = self._clean(tenant_id)
        order = self._clean(order_number)
        if not tid or not order:
            return None

        row = self._session.execute(
            text(
                f"""
                SELECT id::text, order_number, load_type::text
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_ORDER}
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": tid, "order_number": order},
        ).first()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "order_number": row[1] or "",
            "load_type": row[2] or "",
        }

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

    def update_carrier_name(
        self,
        *,
        tenant_id: str,
        tender_id: str,
        carrier_name: str | None,
    ) -> bool:
        """Persist denormalized routing-guide carrier name (nullable)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        if not tid or not tr:
            return False

        cleaned_name = self._clean(carrier_name)

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET carrier_name = :carrier_name, updated_at = NOW()
                {_WHERE_TENANT_TENDER_PK}
                """
            ),
            {
                "carrier_name": cleaned_name,
                "tender_id": tr,
                "tenant_id": tid,
            },
        )
        return result.rowcount > 0

    def insert_batch(self, rows: list[dict[str, Any]]) -> list[TenderInsertResult]:
        """Insert one tender row per input dict; duplicate order numbers are allowed (order rollover)."""
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
                metadata
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
                CAST(:metadata AS jsonb)
            )
            RETURNING id::text
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
                },
            ).first()
            if row and row[0]:
                results.append(
                    TenderInsertResult(
                        tender_id=str(row[0]),
                        created=True,
                    )
                )

        return results
