"""Persist driver name/phone from driver-assignment workflow onto shipments."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.integrations.turvo.shipments import assigned_driver_contact_from_payload
from app.services.shipments_service import ShipmentsService
from app.tools.driver_details import DO_NOTHING, driver_block_name_phone

logger = get_logger(__name__)


class DriverAssignmentShipmentDetailsService:
    def __init__(
        self,
        *,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._shipments = shipments_service or ShipmentsService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _driver_from_state_data(data: dict[str, Any]) -> dict[str, str | None]:
        extraction = data.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        return driver if isinstance(driver, dict) else {}

    def _scope_from_state(self, state) -> tuple[str, str] | None:
        data = getattr(state, "data", {}) or {}
        tenant_id = self._clean(getattr(state, "tenant_id", None) or data.get("tenant_id"))
        shipment_row_id = self._clean(data.get("shipments_row_id"))
        if not tenant_id or not shipment_row_id:
            return None
        return tenant_id, shipment_row_id

    def _persist(
        self,
        state,
        *,
        name: str | None,
        phone: str | None,
        source: str,
    ) -> None:
        if not name and not phone:
            return

        scope = self._scope_from_state(state)
        if scope is None:
            logger.warning(
                "persist shipment driver_details skipped missing scope source=%s",
                source,
            )
            return

        tenant_id, shipment_row_id = scope
        try:
            ok = self._shipments.merge_driver_details(
                tenant_id=tenant_id,
                shipment_row_id=shipment_row_id,
                name=name,
                phone=phone,
            )
        except Exception:
            logger.exception(
                "persist shipment driver_details failed tenant_id=%s shipment_row_id=%s source=%s",
                tenant_id,
                shipment_row_id,
                source,
            )
            return

        if not ok:
            logger.warning(
                "persist shipment driver_details shipment not found tenant_id=%s shipment_row_id=%s source=%s",
                tenant_id,
                shipment_row_id,
                source,
            )

    def persist_extracted_from_state(self, state) -> None:
        data = getattr(state, "data", {}) or {}
        decision = str(data.get("driver_details_decision") or DO_NOTHING).strip()
        if decision == DO_NOTHING:
            return

        driver = self._driver_from_state_data(data)
        name, phone = driver_block_name_phone(driver)
        self._persist(state, name=name, phone=phone, source="extracted")

    def persist_tms_matched_from_state(self, state) -> None:
        data = getattr(state, "data", {}) or {}
        driver = self._driver_from_state_data(data)
        fallback_name, fallback_phone = driver_block_name_phone(driver)
        name = self._clean(data.get("tms_matched_driver_name")) or fallback_name
        phone = self._clean(data.get("tms_matched_driver_phone")) or fallback_phone
        self._persist(state, name=name, phone=phone, source="tms_matched")

    def persist_from_turvo_shipment(self, state) -> None:
        data = getattr(state, "data", None) or {}
        shipment = data.get("shipment")
        if not isinstance(shipment, dict):
            return
        contact = assigned_driver_contact_from_payload(shipment)
        self._persist(
            state,
            name=self._clean(contact.get("name")),
            phone=self._clean(contact.get("phone")),
            source="turvo_shipment",
        )
