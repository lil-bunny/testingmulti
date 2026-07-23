"""Weekend-shifted pickup TMS writes for appointment scheduling confirm."""

from __future__ import annotations

from app.core.asyncio_util import run_sync
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.appointment_scheduling.settings import skip_ascend_writes_enabled
from app.domain.appointment_scheduling.skip_reasons import scheduling_failure_from_skip
from app.domain.error_catalog import IntegrationError
from app.integrations.ascend.appointments import get_loc_ref_for_ascend_slots, update_appointment
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.error_mapping import catalog_from_ascend_api_error
from app.integrations.ascend.errors import AscendApiError
from app.services.appointment_scheduling.ascend_settings import (
    load_appointment_scheduling_settings,
)
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    get_shipment,
    pickup_stop_name_from_payload,
    update_stop_appointment_time,
)
from app.tools.appointment_scheduling.ascend_pickup_update import plan_ascend_pickup_update
from app.tools.appointment_scheduling.weekend_shifted import is_weekend_shifted_truthy
from app.services.shipments_service import ShipmentsService

logger = get_logger(__name__)


@dataclass(frozen=True)
class WeekendPickupResult:
    ok: bool
    skipped: bool = False
    dry_run: bool = False
    failure: SchedulingFailure | None = None
    ascend_updated: bool = False
    turvo_updated: bool = False
    turvo_pickup_start_time: str | None = None
    pickup_stop_name: str | None = None
    ascend_response: dict[str, Any] | None = None
    turvo_response: dict[str, Any] | None = None

    @property
    def error(self) -> str | None:
        return self.failure.message if self.failure else None


class AppointmentSchedulingWeekendPickupService:
    def apply_from_state(self, state) -> WeekendPickupResult:
        data = state.data or {}
        decision = data.get("llm_scheduling_decision") or {}
        if not isinstance(decision, dict):
            decision = {}
        if not is_weekend_shifted_truthy(decision.get("weekend_shifted")):
            return WeekendPickupResult(ok=True, skipped=True)

        tenant_settings = data.get("tenant_settings") or {}
        reference_number = str(data.get("reference_number") or "").strip()
        tenant_slug = str(data.get("tenant_slug") or "").strip()
        shipment_id = str(data.get("shipment_id") or "").strip()
        selected_date = decision.get("selected_pickup_date")
        selected_time = decision.get("selected_pickup_time")

        ascend_ctx = data.get("ascend_context") if isinstance(data.get("ascend_context"), dict) else {}
        appointments = ascend_ctx.get("appointments")

        plan = plan_ascend_pickup_update(appointments, selected_date, selected_time)
        if not plan.should_apply:
            return WeekendPickupResult(ok=True, skipped=True)

        if skip_ascend_writes_enabled(tenant_settings):
            logger.info(
                "skip_ascend_writes dry-run weekend pickup reference=%s plan=%s",
                reference_number,
                plan,
            )
            return WeekendPickupResult(
                ok=True,
                skipped=True,
                dry_run=True,
                turvo_pickup_start_time=plan.turvo_pickup_start_time,
            )

        settings = load_appointment_scheduling_settings(tenant_slug)
        if not settings.ascend_email or not settings.ascend_password:
            failure = scheduling_failure_from_skip("ascend_not_configured")
            if failure is None:
                failure = SchedulingFailure.from_catalog(
                    IntegrationError.VENDOR_API_ERROR,
                    "Ascend credentials are not configured.",
                )
            return WeekendPickupResult(ok=False, failure=failure)

        office_code = ascend_office_code_from_reference(reference_number=reference_number) or ""
        try:
            token_data = login_ascend_api(
                email=str(settings.ascend_email),
                password=str(settings.ascend_password),
            )
            access_token = str(token_data.get("accessToken") or "")
            if appointments is None and reference_number:
                appointments = get_loc_ref_for_ascend_slots(
                    reference_number=reference_number,
                    access_token=access_token,
                    office_code=office_code,
                )
                plan = plan_ascend_pickup_update(appointments, selected_date, selected_time)
                if not plan.should_apply:
                    return WeekendPickupResult(ok=True, skipped=True)

            if not plan.update_body or not plan.appointment_id:
                failure = scheduling_failure_from_skip(
                    "invalid_ascend_pickup_plan",
                    reference_number=reference_number,
                )
                if failure is None:
                    failure = SchedulingFailure.from_catalog(
                        IntegrationError.VENDOR_API_ERROR,
                        "Invalid Ascend pickup plan.",
                    )
                return WeekendPickupResult(ok=False, failure=failure)

            ascend_response = update_appointment(
                appointment_id=plan.appointment_id,
                body=plan.update_body,
                access_token=access_token,
                office_code=office_code,
            )
        except AscendApiError as exc:
            logger.warning(
                "ascend pickup update failed reference=%s: %s",
                reference_number,
                exc,
            )
            catalog, message = catalog_from_ascend_api_error(
                exc,
                operation="pickup_update",
                reference_number=reference_number,
            )
            return WeekendPickupResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(catalog, message),
            )

        turvo_result = self._apply_turvo_pickup(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
            shipment_payload=data.get("shipment") if isinstance(data.get("shipment"), dict) else None,
            start_time=str(plan.turvo_pickup_start_time or ""),
        )
        if not turvo_result.get("ok"):
            turvo_msg = str(turvo_result.get("error") or "turvo_pickup_update_failed")
            return WeekendPickupResult(
                ok=False,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    turvo_msg,
                ),
                ascend_updated=True,
                turvo_pickup_start_time=plan.turvo_pickup_start_time,
                pickup_stop_name=turvo_result.get("stop_name"),
                ascend_response=ascend_response,
                turvo_response=turvo_result,
            )

        tenant_id = str(data.get("tenant_id") or "").strip()
        load_id = str(data.get("load_id") or "").strip()
        customer_name_override = str(data.get("customer_name") or "").strip() or None
        if tenant_id and load_id:
            refresh = ShipmentsService().refresh_display_from_turvo_sync(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                turvo_shipment_id=shipment_id,
                load_id=load_id,
                customer_name_override=customer_name_override,
            )
            if not refresh.get("success"):
                logger.warning(
                    "shipment display refresh failed after turvo pickup update shipment_id=%s: %s",
                    shipment_id,
                    refresh.get("message"),
                )

        return WeekendPickupResult(
            ok=True,
            ascend_updated=True,
            turvo_updated=bool(turvo_result.get("updated")),
            turvo_pickup_start_time=plan.turvo_pickup_start_time,
            pickup_stop_name=str(turvo_result.get("stop_name") or "") or None,
            ascend_response=ascend_response,
            turvo_response=turvo_result,
        )

    @staticmethod
    def _apply_turvo_pickup(
        *,
        tenant_slug: str,
        shipment_id: str,
        shipment_payload: dict[str, Any] | None,
        start_time: str,
    ) -> dict[str, Any]:
        slug = str(tenant_slug or "").strip()
        sid = str(shipment_id or "").strip()
        wall_time = str(start_time or "").strip()
        if not slug or not sid or not wall_time:
            return {"ok": False, "error": "missing_turvo_pickup_fields"}

        payload = shipment_payload
        try:
            if payload is None:
                payload = run_sync(get_shipment(slug, sid))
            stop_name = str(pickup_stop_name_from_payload(payload or {}) or "").strip()
            if not stop_name:
                return {"ok": False, "error": "missing_pickup_stop_name"}
            return run_sync(
                update_stop_appointment_time(
                    slug,
                    sid,
                    stop_name=stop_name,
                    start_time=wall_time,
                    shipment_payload=payload,
                )
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo pickup update failed shipment_id=%s: %s",
                sid,
                exc,
            )
            return {"ok": False, "error": str(exc)}


__all__ = ("AppointmentSchedulingWeekendPickupService", "WeekendPickupResult")
