"""Reads for ``routing_guide`` lane lookup."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import jsonb_param, parse_json
from app.domain.routing_guide import (
    RoutingGuideRow,
    customer_aliases_from_value,
    normalize_plan_carriers,
    plan_carriers_to_json,
)


class RoutingGuideRepository:
    TABLE_NAME = "routing_guide"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _parse_jsonb_value(raw: Any) -> Any:
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    def list_by_tenant_zipcode(
        self,
        *,
        tenant_id: str,
        zipcode: str,
    ) -> list[RoutingGuideRow]:
        """Rows for zip-first lookup; called by ``RoutingGuideLookupService``."""
        tid = self._clean(tenant_id)
        zc = self._clean(zipcode)
        if not tid or not zc:
            return []

        rows = self._session.execute(
            text(
                f"""
                SELECT
                    id::text,
                    customer_name,
                    zipcode,
                    city,
                    state,
                    metadata,
                    customer_aliases,
                    carriers
                FROM {self.TABLE_NAME}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND zipcode = :zipcode
                ORDER BY customer_name ASC, id ASC
                """
            ),
            {"tenant_id": tid, "zipcode": zc},
        ).all()

        out: list[RoutingGuideRow] = []
        for row in rows:
            metadata = parse_json(row[5])
            if not isinstance(metadata, dict):
                metadata = {}
            out.append(
                RoutingGuideRow(
                    id=str(row[0]),
                    customer_name=str(row[1] or "").strip(),
                    zipcode=str(row[2] or "").strip(),
                    city=str(row[3] or "").strip(),
                    state=str(row[4] or "").strip(),
                    metadata=metadata,
                    customer_aliases=customer_aliases_from_value(
                        self._parse_jsonb_value(row[6])
                    ),
                    carriers=normalize_plan_carriers(self._parse_jsonb_value(row[7])),
                )
            )
        return out

    def insert_batch(
        self,
        *,
        tenant_id: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Insert guide rows; ignores duplicates on (tenant, customer_name, zipcode)."""
        tid = self._clean(tenant_id)
        if not tid or not rows:
            return 0

        inserted = 0
        for row in rows:
            customer_name = self._clean(row.get("customer_name"))
            zipcode = self._clean(row.get("zipcode"))
            if not customer_name or not zipcode:
                continue
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            aliases = customer_aliases_from_value(row.get("customer_aliases"))
            city = self._clean(row.get("city")) or ""
            state = self._clean(row.get("state")) or ""
            carriers = normalize_plan_carriers(row.get("carriers"))
            result = self._session.execute(
                text(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        tenant_id,
                        customer_name,
                        zipcode,
                        city,
                        state,
                        metadata,
                        customer_aliases,
                        carriers
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid),
                        :customer_name,
                        :zipcode,
                        :city,
                        :state,
                        CAST(:metadata AS jsonb),
                        CAST(:customer_aliases AS jsonb),
                        CAST(:carriers AS jsonb)
                    )
                    ON CONFLICT ON CONSTRAINT routing_guide_tenant_customer_zip_unique
                    DO NOTHING
                    """
                ),
                {
                    "tenant_id": tid,
                    "customer_name": customer_name,
                    "zipcode": zipcode,
                    "city": city,
                    "state": state,
                    "metadata": jsonb_param(metadata),
                    "customer_aliases": jsonb_param(aliases),
                    "carriers": jsonb_param(plan_carriers_to_json(carriers)),
                },
            )
            inserted += int(result.rowcount or 0)
        return inserted
