"""Ascend dropoff appointment write for appointment scheduling replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.appointment_scheduling.settings import skip_ascend_writes_enabled
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError
from app.integrations.ascend.shipments import fetched_shipment_details, update_shipment_stops
from app.tools.appointment_scheduling.customer_reply import (
    build_ascend_dropoff_update_payload,
    extract_dropoff_stop,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class AscendWriteResult:
    ok: bool
    skipped: bool = False
    dry_run: bool = False
    error: str | None = None
    payload: dict[str, Any] | None = None
    response: dict[str, Any] | None = None


class AppointmentSchedulingAscendWriteService:
    def apply_dropoff_from_state(self, state) -> AscendWriteResult:
        data = state.data or {}
        tenant_settings = data.get("tenant_settings") or {}
        extraction = data.get("customer_reply_extraction") or {}
        if not isinstance(extraction, dict):
            extraction = {}
        ascend_shipment = data.get("ascend_shipment")
        if not isinstance(ascend_shipment, dict):
            ascend_shipment = None
        reference_number = str(data.get("reference_number") or "").strip()
        iso_start = str(
            extraction.get("appointment_start_iso") or data.get("confirmed_delivery_at") or ""
        ).strip()
        return self.apply_dropoff(
            tenant_settings=tenant_settings,
            reference_number=reference_number,
            appointment_start_iso=iso_start,
            ascend_shipment=ascend_shipment,
        )

    def apply_dropoff(
        self,
        *,
        tenant_settings: dict[str, Any],
        reference_number: str,
        appointment_start_iso: str,
        ascend_shipment: dict[str, Any] | None = None,
    ) -> AscendWriteResult:
        ref = str(reference_number or "").strip()
        iso_start = str(appointment_start_iso or "").strip()
        if not ref or not iso_start:
            return AscendWriteResult(ok=False, error="missing_reference_or_appointment_time")

        dropoff = extract_dropoff_stop(ascend_shipment or {})
        if not dropoff.get("stop_id"):
            dropoff = {"stop_id": "dry-run", "stop_number": ""}
        payload = build_ascend_dropoff_update_payload(dropoff, iso_start)

        if skip_ascend_writes_enabled(tenant_settings):
            logger.info(
                "skip_ascend_writes dry-run reference=%s payload=%s",
                ref,
                payload,
            )
            return AscendWriteResult(
                ok=True,
                skipped=True,
                dry_run=True,
                payload=payload,
            )

        settings = T3raAppointmentSchedulingSettings.model_validate(
            tenant_settings.get("appointment_scheduling") or {}
        )
        if not settings.ascend_email or not settings.ascend_password:
            return AscendWriteResult(ok=False, error="missing_ascend_credentials", payload=payload)

        office_code = ascend_office_code_from_reference(reference_number=ref) or ""
        try:
            token_data = login_ascend_api(
                email=str(settings.ascend_email),
                password=str(settings.ascend_password),
            )
            access_token = str(token_data.get("accessToken") or "")
            shipment = fetched_shipment_details(
                reference_number=ref,
                access_token=access_token,
                office_code=office_code,
            )
            dropoff = extract_dropoff_stop(shipment)
            payload = build_ascend_dropoff_update_payload(dropoff, iso_start)
            if not payload:
                return AscendWriteResult(ok=False, error="invalid_ascend_payload")
            response = update_shipment_stops(
                reference_number=ref,
                access_token=access_token,
                office_code=office_code,
                payload=payload,
            )
            return AscendWriteResult(ok=True, payload=payload, response=response)
        except AscendApiError as exc:
            logger.warning("ascend dropoff update failed reference=%s: %s", ref, exc)
            return AscendWriteResult(ok=False, error=str(exc), payload=payload)


__all__ = ("AppointmentSchedulingAscendWriteService", "AscendWriteResult")
