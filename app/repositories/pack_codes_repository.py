"""Read ``pack_codes`` for tenant-scoped ingest resolution."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts, fetchone_dict


class PackCodesRepository:
    TABLE_NAME = "pack_codes"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _normalize_pack_code(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

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
        """Return one pack code row for the tenant keyed by business ``pack_code``."""
        tid = self._clean(tenant_id)
        c = self._clean(code)
        if not tid or not c:
            return None

        row = fetchone_dict(
            self._session,
            f"""
            SELECT
                id::text AS id,
                tenant_id::text AS tenant_id,
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
            WHERE tenant_id = CAST(:tenant_id AS uuid) AND pack_code = :code
            LIMIT 1
            """,
            {"tenant_id": tid, "code": c},
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "pack_code": row.get("pack_code") or "",
            "description": row.get("description") or "",
            "units_per_pallet": self._to_decimal(row.get("units_per_pallet")),
            "qty_per_unit": self._to_decimal(row.get("qty_per_unit")),
            "total_qty": self._to_decimal(row.get("total_qty")),
            "unit_dims": row.get("unit_dims") or "",
            "pallet_dims": row.get("pallet_dims") or "",
            "pallet_type": row.get("pallet_type") or "",
            "is_active": bool(row.get("is_active"))
            if row.get("is_active") is not None
            else True,
        }

    def active_pack_code_id_index(self, *, tenant_id: str) -> dict[str, str]:
        """
        Map trimmed ``pack_codes.pack_code`` text → ``pack_codes.id`` for active rows.

        Lookup at ingest is exact match on trimmed text (no numeric normalization).
        """
        tid = str(tenant_id).strip()
        if not tid:
            return {}

        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT id::text AS id, pack_code
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND is_active IS TRUE
            """,
            {"tenant_id": tid},
        )

        index: dict[str, str] = {}
        for row in rows:
            key = self._normalize_pack_code(row.get("pack_code"))
            pid = row.get("id")
            if key and pid:
                index[key] = str(pid)
        return index
