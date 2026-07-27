"""Ascend dropoff appointment write for appointment scheduling replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.appointment_scheduling.settings import (
    load_appointment_scheduling_settings,
    skip_ascend_writes_enabled,
)
from app.domain.appointment_scheduling.state_hygiene import slim_ascend_write_result
from app.domain.error_catalog import BusinessError, IntegrationError
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError, AscendError, is_ascend_timeout
from app.integrations.ascend.shipments import fetched_shipment_details, update_shipment_stops
from app.services.appointment_scheduling.activity_service import ActivityService
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
    failure: SchedulingFailure | None = None
    payload: dict[str, Any] | None = None
    response: dict[str, Any] | None = None

    @property
    def error(self) -> str | None:
        return self.failure.message if self.failure else None

    def to_checkpoint_dict(self) -> dict[str, Any]:
        return slim_ascend_write_result(
            ok=self.ok,
            skipped=self.skipped,
            dry_run=self.dry_run,
            error=self.error,
        )


@dataclass(frozen=True)
class AscendStateContext:
    tenant_slug: str
    tenant_settings: dict[str, Any]
    reference_number: str
    appointment_start_iso: str
    ascend_shipment: dict[str, Any] | None


def _ascend_context_from_data(data: dict[str, Any]) -> AscendStateContext:
    extraction = data.get("customer_reply_extraction") or {}
    if not isinstance(extraction, dict):
        extraction = {}
    ascend_shipment = data.get("ascend_shipment")
    if not isinstance(ascend_shipment, dict):
        ascend_shipment = None
    return AscendStateContext(
        tenant_slug=str(data.get("tenant_slug") or "").strip(),
        tenant_settings=data.get("tenant_settings") or {},
        reference_number=str(data.get("reference_number") or "").strip(),
        appointment_start_iso=str(
            extraction.get("appointment_start_iso") or data.get("confirmed_delivery_at") or ""
        ).strip(),
        ascend_shipment=ascend_shipment,
    )


class AscendWriteService:
    def __init__(
        self,
        *,
        activity_service: ActivityService | None = None,
    ) -> None:
        self._activity = activity_service or ActivityService()

    def apply_dropoff_from_state(self, state) -> AscendWriteResult:
        ctx = _ascend_context_from_data(state.data or {})
        result = self.apply_dropoff(
            tenant_slug=ctx.tenant_slug,
            tenant_settings=ctx.tenant_settings,
            reference_number=ctx.reference_number,
            appointment_start_iso=ctx.appointment_start_iso,
            ascend_shipment=ctx.ascend_shipment,
        )
        state.data["ascend_update_result"] = result.to_checkpoint_dict()
        self._activity.record_ascend_update(state)
        return result

    def apply_dropoff(
        self,
        *,
        tenant_slug: str,
        tenant_settings: dict[str, Any],
        reference_number: str,
        appointment_start_iso: str,
        ascend_shipment: dict[str, Any] | None = None,
    ) -> AscendWriteResult:
        ref = str(reference_number or "").strip()
        iso_start = str(appointment_start_iso or "").strip()
        if not ref or not iso_start:
            return AscendWriteResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(
                    BusinessError.ASCEND_MISSING_REFERENCE,
                    reference_number=ref,
                ),
            )

        if skip_ascend_writes_enabled(tenant_settings):
            dropoff = extract_dropoff_stop(ascend_shipment or {})
            if not dropoff and tenant_slug:
                dropoff = self._fetch_dropoff_stop(tenant_slug=tenant_slug, reference_number=ref)
            payload = build_ascend_dropoff_update_payload(dropoff, iso_start)
            if not payload:
                return AscendWriteResult(
                    ok=False,
                    failure=SchedulingFailure.from_catalog(
                        BusinessError.ASCEND_INVALID_PAYLOAD,
                        reference_number=ref,
                    ),
                )
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

        settings = load_appointment_scheduling_settings(tenant_slug)
        if not settings.ascend_email or not settings.ascend_password:
            return AscendWriteResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(BusinessError.ASCEND_NOT_CONFIGURED),
            )

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
                return AscendWriteResult(
                    ok=False,
                    failure=SchedulingFailure.from_catalog(
                        BusinessError.ASCEND_INVALID_PAYLOAD,
                        reference_number=ref,
                    ),
                )
            response = update_shipment_stops(
                reference_number=ref,
                access_token=access_token,
                office_code=office_code,
                payload=payload,
            )
            return AscendWriteResult(ok=True, payload=payload, response=response)
        except AscendApiError as exc:
            logger.warning("ascend dropoff update failed reference=%s: %s", ref, exc)
            if is_ascend_timeout(exc):
                failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
            else:
                failure = SchedulingFailure.from_ascend(
                    AscendError.DROPOFF_UPDATE_FAILED,
                    reference_number=ref,
                    status_code=str(exc.status_code or ""),
                )
            return AscendWriteResult(ok=False, failure=failure)

    @staticmethod
    def _fetch_dropoff_stop(*, tenant_slug: str, reference_number: str) -> dict[str, Any]:
        settings = load_appointment_scheduling_settings(tenant_slug)
        if not settings.ascend_email or not settings.ascend_password:
            return {}
        office_code = ascend_office_code_from_reference(reference_number=reference_number) or ""
        try:
            token_data = login_ascend_api(
                email=str(settings.ascend_email),
                password=str(settings.ascend_password),
            )
            access_token = str(token_data.get("accessToken") or "")
            shipment = fetched_shipment_details(
                reference_number=reference_number,
                access_token=access_token,
                office_code=office_code,
            )
            return extract_dropoff_stop(shipment)
        except AscendApiError:
            return {}


__all__ = ("AscendWriteService", "AscendWriteResult")
