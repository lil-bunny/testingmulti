"""All raw SQL reads for ``tender_products``."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import jsonb_param, parse_json


class TenderProductsRepository:
    TABLE_NAME = "tender_products"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def list_by_tender_id(
        self, *, tenant_id: str, tender_id: str
    ) -> list[dict[str, Any]]:
        """Product lines for an order with ``pack_codes`` join (``created_at``, ``id`` order)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        if not tid or not tr:
            return []

        rows = self._session.execute(
            text(
                f"""
                SELECT
                    tp.id,
                    tp.tender_id,
                    tp.product_name,
                    tp.order_quantity,
                    tp.price_per_unit,
                    tp.pack_code_id,
                    tp.metadata,
                    pc.pack_code,
                    pc.description,
                    pc.qty_per_unit,
                    pc.total_qty,
                    pc.units_per_pallet,
                    pc.unit_dims,
                    pc.pallet_dims,
                    pc.pallet_type,
                    pc.is_active,
                    tp.weight_unit::text
                FROM {self.TABLE_NAME} tp
                LEFT JOIN pack_codes pc ON pc.id = tp.pack_code_id
                WHERE tp.tenant_id = CAST(:tenant_id AS uuid) AND tp.tender_id = CAST(:tender_id AS uuid)
                ORDER BY tp.created_at ASC, tp.id ASC
                """
            ),
            {"tenant_id": tid, "tender_id": tr},
        ).all()

        products: list[dict[str, Any]] = []
        for row in rows:
            metadata = parse_json(row[6])
            pack_meta = (
                (metadata.get("pack_code") or {})
                if isinstance(metadata, dict)
                else {}
            )
            amount_from_pc = self._to_decimal(row[9])
            total_from_pc = self._to_decimal(row[10])
            amount_raw = amount_from_pc or self._to_decimal(
                pack_meta.get("qty_per_unit")
            )
            total_raw = total_from_pc or self._to_decimal(
                pack_meta.get("total_qty")
            )
            desc = row[8] or ""
            products.append(
                {
                    "id": str(row[0]),
                    "tender_id": str(row[1]),
                    "product_name": row[2] or "",
                    "order_quantity": row[3],
                    "price_per_unit": self._to_decimal(row[4]),
                    "pack_code_id": str(row[5]) if row[5] else None,
                    "metadata": metadata,
                    "pack_code": row[7] or "",
                    "pack_code_description": desc,
                    "pack_code_name": desc,
                    "qty_per_unit": amount_raw,
                    "total_qty": total_raw,
                    "units_per_pallet": self._to_decimal(row[11]),
                    "unit_dims": row[12] or "",
                    "pallet_dims": row[13] or "",
                    "pallet_type": row[14] or "",
                    "pack_is_active": row[15],
                    "weight_unit": row[16] or "",
                }
            )
        return products

    def existing_line_keys(
        self, *, tender_id: str
    ) -> set[tuple[str, Decimal, str | None]]:
        """Existing product lines for a tender (business-key de-dupe on re-import)."""
        rows = self._session.execute(
            text(
                f"""
                SELECT product_name, order_quantity, pack_code_id::text
                FROM {self.TABLE_NAME}
                WHERE tender_id = CAST(:tender_id AS uuid)
                """
            ),
            {"tender_id": tender_id},
        ).all()

        keys: set[tuple[str, Decimal, str | None]] = set()
        for product_name, order_quantity, pack_code_id in rows:
            keys.add(
                (
                    str(product_name),
                    Decimal(str(order_quantity)),
                    str(pack_code_id) if pack_code_id else None,
                )
            )
        return keys

    def insert_batch(self, rows: list[dict[str, Any]]) -> int:
        """Insert product lines; returns count of rows attempted (including conflicts)."""
        if not rows:
            return 0

        insert_sql = text(
            f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                tender_id,
                pack_code_id,
                product_name,
                order_quantity,
                price_per_unit,
                metadata,
                weight_unit
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:tender_id AS uuid),
                CAST(:pack_code_id AS uuid),
                :product_name,
                :order_quantity,
                :price_per_unit,
                CAST(:metadata AS jsonb),
                CAST(:weight_unit AS weight_unit)
            )
            """
        )
        for r in rows:
            self._session.execute(
                insert_sql,
                {
                    "tenant_id": r["tenant_id"],
                    "tender_id": r["tender_id"],
                    "pack_code_id": r.get("pack_code_id"),
                    "product_name": r["product_name"],
                    "order_quantity": r["order_quantity"],
                    "price_per_unit": r.get("price_per_unit"),
                    "metadata": jsonb_param(r.get("metadata") or {}),
                    "weight_unit": r.get("weight_unit"),
                },
            )

        return len(rows)
