"""Weekend-shifted pickup TMS writes for appointment scheduling confirm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.scheduling_reference import ascend_office_code_from_reference
from app.domain.appointment_scheduling.settings import skip_ascend_writes_enabled
from app.domain.error_catalog import BusinessError, IntegrationError
from app.integrations.ascend.appointments import get_loc_ref_for_ascend_slots, update_appointment
from app.integrations.ascend.errors import AscendApiError, AscendError, is_ascend_timeout
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    get_shipment,
    pickup_stop_name_from_payload,
    update_stop_appointment_time,
)
from app.domain.appointment_scheduling.state_hygiene import slim_weekend_pickup_result
from app.tools.appointment_scheduling.ascend_pickup_update import plan_ascend_pickup_update
from app.tools.appointment_scheduling.dates import is_weekend_shifted_truthy
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)
from app.services.ascend_oauth_service import AscendOAuthService
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

    def to_checkpoint_dict(self) -> dict[str, Any]:
        return slim_weekend_pickup_result(
            ok=self.ok,
            skipped=self.skipped,
            dry_run=self.dry_run,
            error=self.error,
            ascend_updated=self.ascend_updated,
            turvo_updated=self.turvo_updated,
            turvo_pickup_start_time=self.turvo_pickup_start_time,
            pickup_stop_name=self.pickup_stop_name,
        )


class WeekendPickupService:
    def __init__(
        self,
        *,
        activity_service: ActivityService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._activity = activity_service or ActivityService()
        self._shipments = shipments_service or ShipmentsService()

    def apply_weekend_shifted_pickup_from_state(self, state) -> WeekendPickupResult:
        result = run_sync(self._apply_weekend_shifted_pickup_from_state(state))
        self._activity.record_weekend_pickup_update(
            state,
            result=result.to_checkpoint_dict(),
        )
        return result

    async def _apply_weekend_shifted_pickup_from_state(self, state) -> WeekendPickupResult:
        data = state.data or {}
        decision = data.get("llm_appointment_decision") or {}
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

        skip_ascend = skip_ascend_writes_enabled(tenant_settings)
        ascend_response: dict[str, Any] | None = None
        ascend_updated = False
        dry_run = False

        if skip_ascend:
            # Ascend HTTP only — Turvo weekend pickup still runs below.
            logger.info(
                "skip_ascend_writes: skipping Ascend HTTP weekend pickup; "
                "continuing Turvo update reference=%s plan=%s",
                reference_number,
                plan,
            )
            dry_run = True
        else:
            access_token = AscendOAuthService().get_access_token(tenant_slug)
            if not access_token:
                return WeekendPickupResult(
                    ok=False,
                    failure=SchedulingFailure.from_catalog(BusinessError.ASCEND_NOT_CONFIGURED),
                )

            office_code = ascend_office_code_from_reference(reference_number=reference_number) or ""
            try:
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
                    return WeekendPickupResult(
                        ok=False,
                        failure=SchedulingFailure.from_catalog(
                            BusinessError.ASCEND_INVALID_PAYLOAD,
                            reference_number=reference_number,
                        ),
                    )

                ascend_response = update_appointment(
                    appointment_id=plan.appointment_id,
                    body=plan.update_body,
                    access_token=access_token,
                    office_code=office_code,
                )
                ascend_updated = True
            except AscendApiError as exc:
                logger.warning(
                    "ascend pickup update failed reference=%s: %s",
                    reference_number,
                    exc,
                )
                if is_ascend_timeout(exc):
                    failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
                else:
                    failure = SchedulingFailure.from_ascend(
                        AscendError.PICKUP_UPDATE_FAILED,
                        reference_number=reference_number,
                        status_code=str(exc.status_code or ""),
                    )
                return WeekendPickupResult(ok=False, failure=failure)

        turvo_result = await self._apply_turvo_pickup(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
            shipment_payload=data.get("shipment") if isinstance(data.get("shipment"), dict) else None,
            start_time=str(plan.turvo_pickup_start_time or ""),
        )
        if not turvo_result.get("ok"):
            turvo_msg = str(turvo_result.get("error") or "turvo_pickup_update_failed")
            return WeekendPickupResult(
                ok=False,
                dry_run=dry_run,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    turvo_msg,
                ),
                ascend_updated=ascend_updated,
                turvo_pickup_start_time=plan.turvo_pickup_start_time,
                pickup_stop_name=turvo_result.get("stop_name"),
                ascend_response=ascend_response,
                turvo_response=turvo_result,
            )

        tenant_id = str(data.get("tenant_id") or "").strip()
        load_id = str(data.get("load_id") or "").strip()
        customer_name_override = str(data.get("customer_name") or "").strip() or None
        if tenant_id and load_id:
            refresh = await self._shipments.refresh_display_from_turvo(
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
            dry_run=dry_run,
            ascend_updated=ascend_updated,
            turvo_updated=bool(turvo_result.get("updated")),
            turvo_pickup_start_time=plan.turvo_pickup_start_time,
            pickup_stop_name=str(turvo_result.get("stop_name") or "") or None,
            ascend_response=ascend_response,
            turvo_response=turvo_result,
        )

    @staticmethod
    async def _apply_turvo_pickup(
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
                payload = await get_shipment(slug, sid)
            stop_name = str(pickup_stop_name_from_payload(payload or {}) or "").strip()
            if not stop_name:
                return {"ok": False, "error": "missing_pickup_stop_name"}
            return await update_stop_appointment_time(
                slug,
                sid,
                stop_name=stop_name,
                start_time=wall_time,
                shipment_payload=payload,
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo pickup update failed shipment_id=%s: %s",
                sid,
                exc,
            )
            return {"ok": False, "error": str(exc)}


__all__ = ("WeekendPickupService", "WeekendPickupResult")
