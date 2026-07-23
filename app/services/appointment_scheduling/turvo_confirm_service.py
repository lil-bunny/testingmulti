"""Turvo delivery placeholder (0001 rule) for appointment scheduling confirm."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.skip_reasons import (
    WIRE_TURVO_SHIPMENT_FETCH_FAILED,
    WIRE_TURVO_STOP_UPDATE_FAILED,
)
from app.domain.error_catalog import IntegrationError
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    delivery_date_only_from_payload,
    delivery_stop_name_from_payload,
    get_shipment,
    update_stop_appointment_time,
)
from app.domain.appointment_scheduling.state_hygiene import slim_turvo_confirm_result
from app.tools.appointment_scheduling.turvo_confirm import prepare_delivery_placeholder

logger = get_logger(__name__)


@dataclass(frozen=True)
class TurvoConfirmResult:
    ok: bool
    updated: bool = False
    error: str | None = None
    failure: SchedulingFailure | None = None
    stop_name: str | None = None
    start_time: str | None = None
    response: dict[str, Any] | None = None

    def to_checkpoint_dict(self) -> dict[str, Any]:
        return slim_turvo_confirm_result(
            ok=self.ok,
            updated=self.updated,
            error=self.error,
            stop_name=self.stop_name,
            start_time=self.start_time,
        )


class AppointmentSchedulingTurvoConfirmService:
    def apply_delivery_placeholder_from_state(self, state) -> TurvoConfirmResult:
        return run_sync(self._apply_delivery_placeholder_from_state_async(state))

    async def _apply_delivery_placeholder_from_state_async(self, state) -> TurvoConfirmResult:
        data = state.data or {}
        tenant_slug = str(data.get("tenant_slug") or "").strip()
        shipment_id = str(data.get("shipment_id") or "").strip()
        payload = data.get("shipment") if isinstance(data.get("shipment"), dict) else None
        return await self.apply_delivery_placeholder(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
            shipment_payload=payload,
        )

    async def apply_delivery_placeholder(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        shipment_payload: dict[str, Any] | None = None,
    ) -> TurvoConfirmResult:
        slug = str(tenant_slug or "").strip()
        sid = str(shipment_id or "").strip()
        if not slug or not sid:
            wire = "missing_turvo_shipment_fields"
            return TurvoConfirmResult(
                ok=False,
                error=wire,
                failure=SchedulingFailure.from_wire(wire, wire.replace("_", " ")),
            )

        payload = shipment_payload
        try:
            if payload is None:
                payload = await get_shipment(slug, sid)
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo confirm shipment fetch failed shipment_id=%s: %s",
                sid,
                exc,
            )
            detail = str(exc)
            return TurvoConfirmResult(
                ok=False,
                error=WIRE_TURVO_SHIPMENT_FETCH_FAILED,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
                    detail,
                ),
            )

        stop_name = str(delivery_stop_name_from_payload(payload or {}) or "").strip()
        delivery_date = delivery_date_only_from_payload(payload or {})
        placeholder = prepare_delivery_placeholder(
            stop_name=stop_name,
            delivery_date=str(delivery_date or ""),
        )
        if placeholder is None:
            wire = "missing_delivery_stop_or_date"
            return TurvoConfirmResult(
                ok=False,
                error=wire,
                failure=SchedulingFailure.from_wire(wire, wire.replace("_", " ")),
                stop_name=stop_name or None,
            )

        try:
            raw = await update_stop_appointment_time(
                slug,
                sid,
                stop_name=placeholder.stop_name,
                start_time=placeholder.start_time,
                shipment_payload=payload,
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo delivery placeholder failed shipment_id=%s stop=%s: %s",
                sid,
                placeholder.stop_name,
                exc,
            )
            detail = str(exc)
            return TurvoConfirmResult(
                ok=False,
                error=WIRE_TURVO_STOP_UPDATE_FAILED,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    detail,
                ),
                stop_name=placeholder.stop_name,
                start_time=placeholder.start_time,
            )

        ok = bool(raw.get("ok"))
        if not ok:
            err = str(raw.get("error") or WIRE_TURVO_STOP_UPDATE_FAILED)
            return TurvoConfirmResult(
                ok=False,
                updated=bool(raw.get("updated")),
                error=WIRE_TURVO_STOP_UPDATE_FAILED,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    err,
                ),
                stop_name=placeholder.stop_name,
                start_time=placeholder.start_time,
                response=raw,
            )

        return TurvoConfirmResult(
            ok=True,
            updated=bool(raw.get("updated")),
            stop_name=placeholder.stop_name,
            start_time=placeholder.start_time,
            response=raw,
        )


__all__ = ("AppointmentSchedulingTurvoConfirmService", "TurvoConfirmResult")
