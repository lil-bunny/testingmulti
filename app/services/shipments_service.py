"""Orchestration for ``shipments`` persistence."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.integrations.turvo.load_to_shipment import load_id_to_shipment_id_async
from app.integrations.turvo.shipments import (
    get_shipment as get_turvo_shipment_async,
    shipment_display_fields_from_payload,
)
from app.tools.driver_details import merge_driver_details_fields

if TYPE_CHECKING:
    from app.repositories.shipments_repository import (
        ShipmentsRepository,
        ShipmentUpsertResult,
    )
    from app.domain.shipment_display import ShipmentDisplayFields

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

    @staticmethod
    def _resolve_display_fields(
        *,
        turvo_payload: dict[str, Any] | None,
        display_fields: ShipmentDisplayFields | None,
    ) -> ShipmentDisplayFields | None:
        if display_fields is not None:
            return display_fields
        if isinstance(turvo_payload, dict):
            return shipment_display_fields_from_payload(turvo_payload)
        return None

    def _upsert_tx(
        self,
        *,
        tenant_id: str,
        shipment_number: str,
        metadata: dict[str, Any],
        display_fields: ShipmentDisplayFields | None,
    ) -> ShipmentUpsertResult:
        kwargs: dict[str, Any] = {
            "tenant_id": tenant_id,
            "shipment_number": shipment_number,
            "metadata": metadata,
        }
        if display_fields is not None:
            kwargs["pickup_date"] = display_fields.pickup_date
            kwargs["pickup_timezone"] = display_fields.pickup_timezone
            kwargs["delivery_date"] = display_fields.delivery_date
            kwargs["delivery_timezone"] = display_fields.delivery_timezone
            kwargs["carrier_name"] = display_fields.carrier_name
            kwargs["customer_name"] = display_fields.customer_name

        if self._shipments is not None:
            return self._shipments.upsert_by_tenant_and_shipment_number_tx(**kwargs)
        return run_with_repos(
            lambda repos: self._repo(repos).upsert_by_tenant_and_shipment_number_tx(
                **kwargs
            )
        )

    def upsert_from_turvo(
        self,
        *,
        tenant_id: str,
        turvo_shipment_id: str,
        load_id: str,
        metadata: dict[str, Any] | None = None,
        turvo_payload: dict[str, Any] | None = None,
        display_fields: ShipmentDisplayFields | None = None,
    ) -> dict[str, Any]:
        """
        Insert or update a shipment row after Turvo id resolution (ratecon path).

        ``shipment_number`` stores the Turvo shipment id. ``metadata`` always includes
        ``load_id``. When ``turvo_payload`` or ``display_fields`` is supplied, also
        persists appointment timestamps, timezones, ``carrier_name``, and ``customer_name``.
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
        fields = self._resolve_display_fields(
            turvo_payload=turvo_payload,
            display_fields=display_fields,
        )

        try:
            result = self._upsert_tx(
                tenant_id=tid,
                shipment_number=number,
                metadata=payload,
                display_fields=fields,
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

    async def upsert_from_load_id(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        load_id: str,
    ) -> dict[str, Any]:
        """Resolve Turvo load, fetch shipment details, upsert ``shipments`` row."""
        load = self._clean(load_id)
        if not load:
            return {"success": False, "message": "missing_load_id"}

        slug = self._clean(tenant_slug)
        if not slug:
            return {"success": False, "message": "missing_tenant_slug"}

        try:
            turvo_shipment_id = await load_id_to_shipment_id_async(slug, load)
        except Exception:
            logger.exception(
                "Turvo load resolve failed tenant_slug=%s load_id=%s",
                slug,
                load,
            )
            return {"success": False, "message": "turvo_load_resolve_failed"}

        if not turvo_shipment_id:
            return {"success": False, "message": "turvo_shipment_not_found"}

        number = str(turvo_shipment_id).strip()
        try:
            turvo_payload = await get_turvo_shipment_async(slug, number)
        except Exception:
            logger.exception(
                "Turvo get_shipment failed tenant_slug=%s shipment_number=%s",
                slug,
                number,
            )
            turvo_payload = None

        return self.upsert_from_turvo(
            tenant_id=tenant_id,
            turvo_shipment_id=number,
            load_id=load,
            turvo_payload=turvo_payload if isinstance(turvo_payload, dict) else None,
        )

    def enrich_display_fields_from_turvo_payload(
        self,
        *,
        tenant_id: str,
        turvo_shipment_id: str,
        load_id: str,
        turvo_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Update display columns using an already-fetched Turvo shipment payload."""
        return self.upsert_from_turvo(
            tenant_id=tenant_id,
            turvo_shipment_id=turvo_shipment_id,
            load_id=load_id,
            turvo_payload=turvo_payload,
        )

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

    @staticmethod
    def _load_id_from_row(row: dict[str, Any] | None) -> str | None:
        if not row:
            return None
        metadata = row.get("metadata")
        if not isinstance(metadata, dict):
            return None
        return ShipmentsService._clean(metadata.get("load_id"))

    def resolve_load_id(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str | None = None,
        shipment_number: str | None = None,
    ) -> str | None:
        """Broker ``load_id`` from ``shipments.metadata`` (set by ratecon upsert)."""
        row_id = self._uuid_or_none(self._clean(shipments_row_id))
        if row_id:
            return self._load_id_from_row(
                self.get_by_id(tenant_id=tenant_id, shipment_id=row_id)
            )
        number = self._clean(shipment_number)
        if number:
            return self._load_id_from_row(
                self.get_by_shipment_number(tenant_id=tenant_id, shipment_number=number)
            )
        return None

    def merge_metadata(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        metadata_patch: dict[str, Any],
    ) -> bool:
        """
        Merge keys into ``shipments.metadata`` for one tenant-scoped row.

        Returns False when ids are invalid or no row matches.
        """
        tid = self._uuid_or_none(tenant_id)
        sid = self._uuid_or_none(shipment_row_id)
        if not tid or not sid or not metadata_patch:
            return False
        if self._shipments is not None:
            return self._shipments.merge_metadata_by_id_tx(
                tenant_id=tid,
                shipment_row_id=sid,
                metadata_patch=metadata_patch,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).merge_metadata_by_id_tx(
                tenant_id=tid,
                shipment_row_id=sid,
                metadata_patch=metadata_patch,
            )
        )

    def merge_driver_details(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        name: str | None = None,
        phone: str | None = None,
    ) -> bool:
        """Merge name/phone into ``shipments.driver_details``; returns False when row missing."""
        tid = self._uuid_or_none(tenant_id)
        sid = self._uuid_or_none(shipment_row_id)
        if not tid or not sid:
            return False

        if self._shipments is not None:
            row = self._shipments.get_by_tenant_and_id_tx(
                tenant_id=tid,
                shipment_id=sid,
            )
        else:
            row = run_with_repos(
                lambda repos: self._repo(repos).get_by_tenant_and_id_tx(
                    tenant_id=tid,
                    shipment_id=sid,
                )
            )
        if not row:
            return False

        merged = merge_driver_details_fields(
            row.get("driver_details"),
            name=name,
            phone=phone,
        )

        if self._shipments is not None:
            self._shipments.merge_driver_details_tx(
                tenant_id=tid,
                shipment_row_id=sid,
                driver_details=merged,
            )
        else:
            run_with_repos(
                lambda repos: self._repo(repos).merge_driver_details_tx(
                    tenant_id=tid,
                    shipment_row_id=sid,
                    driver_details=merged,
                )
            )
        return True

    def update_proposed_appointments(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        proposed_pickup_at: str | None = None,
        proposed_delivery_at: str | None = None,
    ) -> bool:
        """Persist LLM scheduling dates on ``shipments.proposed_*``; no-op when unparseable."""
        from app.tools.appointment_scheduling.proposed_appointments import (
            parse_proposed_appointment_date,
        )

        tid = self._uuid_or_none(tenant_id)
        sid = self._uuid_or_none(shipment_row_id)
        if not tid or not sid:
            return False

        proposed_pickup = parse_proposed_appointment_date(proposed_pickup_at)
        proposed_delivery = parse_proposed_appointment_date(proposed_delivery_at)
        if proposed_pickup is None and proposed_delivery is None:
            return False

        if self._shipments is not None:
            return self._shipments.update_proposed_appointments_tx(
                tenant_id=tid,
                shipment_row_id=sid,
                proposed_pickup=proposed_pickup,
                proposed_delivery=proposed_delivery,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).update_proposed_appointments_tx(
                tenant_id=tid,
                shipment_row_id=sid,
                proposed_pickup=proposed_pickup,
                proposed_delivery=proposed_delivery,
            )
        )

    def clear_driver_details(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
    ) -> bool:
        """Clear ``shipments.driver_details``; returns False when row missing."""
        tid = self._uuid_or_none(tenant_id)
        sid = self._uuid_or_none(shipment_row_id)
        if not tid or not sid:
            return False

        if self._shipments is not None:
            return self._shipments.clear_driver_details_tx(
                tenant_id=tid,
                shipment_row_id=sid,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).clear_driver_details_tx(
                tenant_id=tid,
                shipment_row_id=sid,
            )
        )
