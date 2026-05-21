"""Tender reads (join pack code + locations) and minimal writes for load tendering."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import psycopg

from app.core.config import settings
def _fmt_location(
    city: str | None, state: str | None, state_code: str | None
) -> str:
    city = (city or "").strip()
    region = (state_code or state or "").strip()
    if city and region:
        return f"{city}, {region}"
    return city or region or ""


class TenderService:
    TABLE_NAME = "tenders"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def read_row(
        self, *, tenant_id: str, tender_id: str
    ) -> dict[str, Any] | None:
        """
        Load one tender scoped by tenant UUID, with ``pack_codes`` joined on
        ``t.pack_code_id = pack_codes.id`` and pickup/delivery locations.

        Numeric pack fields prefer the joined ``pack_codes`` row; if the join misses (null or
        orphan ``pack_code_id``), fall back to ``tenders.metadata['pack_code']`` using
        ``qty_per_unit`` / ``total_qty``.
        """
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        if not tid or not tr:
            return None

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        t.id,
                        t.order_number,
                        t.customer_name,
                        t.product_name,
                        t.order_quantity,
                        t.shipping_date,
                        t.delivery_date,
                        t.load_type::text,
                        t.metadata,
                        t.pack_code_id,
                        pc.pack_code,
                        pc.description AS pack_code_description,
                        pc.qty_per_unit,
                        pc.total_qty,
                        pc.units_per_pallet,
                        pc.unit_dims,
                        pc.pallet_dims,
                        pc.pallet_type,
                        pc.is_active,
                        pl.city AS pickup_city,
                        pl.state AS pickup_state,
                        pl.state_code AS pickup_state_code,
                        dl.city AS delivery_city,
                        dl.state AS delivery_state,
                        dl.state_code AS delivery_state_code
                    FROM {self.TABLE_NAME} t
                    LEFT JOIN pack_codes pc ON pc.id = t.pack_code_id
                    LEFT JOIN locations pl ON pl.id = t.pickup_location_id
                    LEFT JOIN locations dl ON dl.id = t.delivery_location_id
                    WHERE t.id = %s::uuid AND t.tenant_id = %s::uuid
                    LIMIT 1
                    """,
                    (tr, tid),
                )
                row = cur.fetchone()
                if not row:
                    return None

                meta = row[8]
                if isinstance(meta, dict):
                    metadata = meta
                elif meta in (None, ""):
                    metadata = {}
                else:
                    metadata = json.loads(meta)

                pack_meta = (metadata.get("pack_code") or {}) if isinstance(metadata, dict) else {}
                amount_from_pc = self._to_decimal(row[12])
                total_from_pc = self._to_decimal(row[13])
                amount_raw = amount_from_pc or self._to_decimal(
                    pack_meta.get("qty_per_unit")
                )
                total_raw = total_from_pc or self._to_decimal(
                    pack_meta.get("total_qty")
                )

                desc = row[11] or ""
                return {
                    "id": str(row[0]),
                    "order_number": row[1] or "",
                    "customer_name": row[2] or "",
                    "product_name": row[3] or "",
                    "order_quantity": row[4],
                    "shipping_date": row[5],
                    "delivery_date": row[6],
                    "load_type": row[7] or "",
                    "metadata": metadata,
                    "pack_code_id": str(row[9]) if row[9] else None,
                    "pack_code": row[10] or "",
                    "pack_code_description": desc,
                    "pack_code_name": desc,
                    "pickup_address": _fmt_location(row[19], row[20], row[21]),
                    "delivery_address": _fmt_location(row[22], row[23], row[24]),
                    "qty_per_unit": amount_raw,
                    "total_qty": total_raw,
                    "units_per_pallet": self._to_decimal(row[14]),
                    "unit_dims": row[15] or "",
                    "pallet_dims": row[16] or "",
                    "pallet_type": row[17] or "",
                    "pack_is_active": row[18],
                }
        finally:
            conn.close()

    def find_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        """Return ``{id, order_number}`` for a tenant-scoped tender row, or ``None``."""
        tid = self._clean(tenant_id)
        order = self._clean(order_number)
        if not tid or not order:
            return None
        conn = self._conn()
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

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def update_load_type(
        self, *, tenant_id: str, tender_id: str, load_type: str
    ) -> bool:
        """Persist ``load_type`` on the tender (``LTL`` / ``FTL`` / ``PARTIAL`` enum labels)."""
        tid = self._clean(tenant_id)
        tr = self._clean(tender_id)
        lt = (load_type or "").strip().upper()
        if not tid or not tr or lt not in {"LTL", "FTL", "PARTIAL"}:
            return False
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET load_type = %s::load_type_enum, updated_at = NOW()
                    WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (lt, tr, tid),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()
