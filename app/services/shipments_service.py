"""Orchestration for ``shipments`` persistence."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.repositories.shipments_repository import (
    ShipmentsRepository,
    ShipmentUpsertResult,
)

logger = get_logger(__name__)


class ShipmentsService:
    def __init__(
        self,
        *,
        shipments_repository: ShipmentsRepository | None = None,
    ) -> None:
        self._shipments = shipments_repository

    def _repo(self, repos: Any) -> ShipmentsRepository:
        return self._shipments or repos.shipments

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _uuid_or_none(value: str | None) -> str | None:
        raw = ShipmentsService._clean(value)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None

    def _build_metadata(
        self,
        *,
        load_id: str,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {"load_id": load_id}
        if not extra:
            return base
        merged = dict(extra)
        merged.pop("load_id", None)
        merged.pop("source", None)
        base.update(merged)
        return base

    def upsert_from_turvo(
        self,
        *,
        tenant_id: str,
        turvo_shipment_id: str,
        load_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Insert or update a shipment row after Turvo id resolution (ratecon path).

        ``shipment_number`` stores the Turvo shipment id. ``metadata`` always includes
        ``load_id``.
        """
        tid = self._uuid_or_none(tenant_id)
        if not tid:
            return {"success": False, "message": "invalid_tenant_id"}

        number = self._clean(turvo_shipment_id)
        if not number:
            return {"success": False, "message": "missing_turvo_shipment_id"}

        load = self._clean(load_id)
        if not load:
            return {"success": False, "message": "missing_load_id"}

        payload = self._build_metadata(load_id=load, extra=metadata)

        try:
            if self._shipments is not None:
                result = self._shipments.upsert_by_tenant_and_shipment_number_tx(
                    tenant_id=tid,
                    shipment_number=number,
                    metadata=payload,
                )
            else:
                result = run_with_repos(
                    lambda repos: self._repo(repos).upsert_by_tenant_and_shipment_number_tx(
                        tenant_id=tid,
                        shipment_number=number,
                        metadata=payload,
                    )
                )
        except Exception:
            logger.exception(
                "shipments upsert failed tenant_id=%s shipment_number=%s load_id=%s",
                tid,
                number,
                load,
            )
            return {"success": False, "message": "shipments_upsert_failed"}

        return {
            "success": True,
            "shipments_row_id": result.shipment_id,
            "created": result.created,
            "shipment_number": number,
        }

    def get_by_shipment_number(
        self,
        *,
        tenant_id: str,
        shipment_number: str,
    ) -> dict[str, Any] | None:
        """Lookup ``shipments`` row by external shipment number (``shipment_number`` column)."""
        tid = self._uuid_or_none(tenant_id)
        number = self._clean(shipment_number)
        if not tid or not number:
            return None
        if self._shipments is not None:
            return self._shipments.get_by_tenant_and_shipment_number_tx(
                tenant_id=tid,
                shipment_number=number,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).get_by_tenant_and_shipment_number_tx(
                tenant_id=tid,
                shipment_number=number,
            )
        )

    def get_by_id(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> dict[str, Any] | None:
        """Lookup ``shipments`` row by primary key (``shipments.id`` UUID)."""
        tid = self._uuid_or_none(tenant_id)
        sid = self._uuid_or_none(shipment_id)
        if not tid or not sid:
            return None
        if self._shipments is not None:
            return self._shipments.get_by_tenant_and_id_tx(
                tenant_id=tid,
                shipment_id=sid,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).get_by_tenant_and_id_tx(
                tenant_id=tid,
                shipment_id=sid,
            )
        )

    def get_by_turvo_shipment_number(
        self,
        *,
        tenant_id: str,
        turvo_shipment_id: str,
    ) -> dict[str, Any] | None:
        """Deprecated: use ``get_by_shipment_number``. Kept for backward compatibility."""
        return self.get_by_shipment_number(
            tenant_id=tenant_id,
            shipment_number=turvo_shipment_id,
        )
