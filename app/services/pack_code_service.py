"""Read-only access to ``pack_codes`` for workflow nodes."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg

from app.core.config import settings


class PackCodeService:
    """Same psycopg + ``DATABASE_URL`` pattern as ``TenantsService`` / ``TenderService``."""

    TABLE_NAME = "pack_codes"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

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

    def get_by_code(self, *, tenant_id: str, code: str) -> dict[str, Any] | None:
        """
        Return one pack code row for the tenant, keyed by business ``pack_code`` (e.g. ``5318``).

        ``qty_per_unit`` and ``total_qty`` match ``pack_codes`` columns from schema v2.
        """
        tid = self._clean(tenant_id)
        c = self._clean(code)
        if not tid or not c:
            return None

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        id,
                        tenant_id,
                        pack_code,
                        description,
                        units_per_pallet,
                        qty_per_unit,
                        total_qty,
                        unit_dims,
                        pallet_dims,
                        pallet_type,
                        is_active
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid AND pack_code = %s
                    LIMIT 1
                    """,
                    (tid, c),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]),
                    "pack_code": row[2] or "",
                    "description": row[3] or "",
                    "units_per_pallet": self._to_decimal(row[4]),
                    "qty_per_unit": self._to_decimal(row[5]),
                    "total_qty": self._to_decimal(row[6]),
                    "unit_dims": row[7] or "",
                    "pallet_dims": row[8] or "",
                    "pallet_type": row[9] or "",
                    "is_active": bool(row[10]) if row[10] is not None else True,
                }
        finally:
            conn.close()
