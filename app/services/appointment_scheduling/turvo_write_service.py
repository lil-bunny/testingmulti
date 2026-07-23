"""Turvo delivery appointment write for appointment scheduling replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.skip_reasons import (
    WIRE_TURVO_SHIPMENT_FETCH_FAILED,
    WIRE_TURVO_STOP_UPDATE_FAILED,
    WIRE_TURVO_TENDER_STATUS_FAILED,
)
from app.domain.error_catalog import IntegrationError
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipment_status import (
    build_tender_status_body,
    fetch_app_shipment_details,
    fragment_id_from_shipment_payload,
    status_code_key_from_shipment_payload,
    timezone_from_shipment_payload,
    update_shipment_tender_status,
)
from app.integrations.turvo.shipments import (
    delivery_stop_name_from_payload,
    get_shipment,
    update_stop_appointment_time,
)
from app.integrations.turvo.webhook_mapping import TENDERED_STATUS_CODE_KEY
from app.services.shipments_service import ShipmentsService

logger = get_logger(__name__)


@dataclass(frozen=True)
class TurvoWriteResult:
    ok: bool
    updated: bool = False
    skipped: bool = False
    error: str | None = None
    failure: SchedulingFailure | None = None
    stop_name: str | None = None
    start_time: str | None = None
    response: dict[str, Any] | None = None


def _wire_failure(wire: str, message: str) -> SchedulingFailure:
    return SchedulingFailure.from_wire(wire, message)


def _turvo_fetch_failure(exc: Exception) -> TurvoWriteResult:
    detail = str(exc)
    return TurvoWriteResult(
        ok=False,
        error=WIRE_TURVO_SHIPMENT_FETCH_FAILED,
        failure=SchedulingFailure.from_catalog(
            IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
            detail,
        ),
    )


def _turvo_stop_failure(exc: Exception, *, stop_name: str | None = None, start_time: str | None = None) -> TurvoWriteResult:
    detail = str(exc)
    return TurvoWriteResult(
        ok=False,
        error=WIRE_TURVO_STOP_UPDATE_FAILED,
        failure=SchedulingFailure.from_catalog(
            IntegrationError.TURVO_STOP_UPDATE_FAILED,
            detail,
        ),
        stop_name=stop_name,
        start_time=start_time,
    )


class AppointmentSchedulingTurvoWriteService:
    def apply_delivery_from_state(self, state) -> TurvoWriteResult:
        return run_sync(self._apply_delivery_from_state_async(state))

    async def _apply_delivery_from_state_async(self, state) -> TurvoWriteResult:
        data = state.data or {}
        extraction = data.get("customer_reply_extraction") or {}
        if not isinstance(extraction, dict):
            extraction = {}
        tenant_slug = str(data.get("tenant_slug") or "").strip()
        shipment_id = str(data.get("shipment_id") or "").strip()
        start_time = str(
            extraction.get("turvo_start_time") or data.get("confirmed_delivery_at") or ""
        ).strip()
        return await self.apply_delivery(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
            start_time=start_time,
            shipment_payload=data.get("shipment") if isinstance(data.get("shipment"), dict) else None,
            tenant_id=str(data.get("tenant_id") or "").strip(),
            load_id=str(data.get("load_id") or "").strip(),
            customer_name_override=str(data.get("customer_name") or "").strip() or None,
        )

    async def apply_delivery(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        start_time: str,
        stop_name: str = "",
        shipment_payload: dict[str, Any] | None = None,
        tenant_id: str = "",
        load_id: str = "",
        customer_name_override: str | None = None,
    ) -> TurvoWriteResult:
        slug = str(tenant_slug or "").strip()
        sid = str(shipment_id or "").strip()
        wall_time = str(start_time or "").strip()

        payload = shipment_payload if isinstance(shipment_payload, dict) else None
        if payload is None and slug and sid:
            try:
                payload = await get_shipment(slug, sid)
            except (TurvoApiError, ValueError) as exc:
                logger.warning(
                    "turvo delivery update shipment fetch failed shipment_id=%s: %s",
                    sid,
                    exc,
                )
                return _turvo_fetch_failure(exc)

        name = str(stop_name or "").strip()
        if not name and payload is not None:
            name = str(delivery_stop_name_from_payload(payload) or "").strip()

        if not slug or not sid or not name or not wall_time:
            wire = "missing_turvo_update_fields"
            return TurvoWriteResult(
                ok=False,
                error=wire,
                failure=_wire_failure(wire, wire.replace("_", " ")),
            )

        try:
            raw = await update_stop_appointment_time(
                slug,
                sid,
                stop_name=name,
                start_time=wall_time,
                shipment_payload=payload,
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo delivery update failed shipment_id=%s stop=%s: %s",
                sid,
                name,
                exc,
            )
            return _turvo_stop_failure(exc, stop_name=name, start_time=wall_time)

        ok = bool(raw.get("ok"))
        if not ok:
            err = str(raw.get("error") or WIRE_TURVO_STOP_UPDATE_FAILED)
            return TurvoWriteResult(
                ok=False,
                updated=bool(raw.get("updated")),
                error=WIRE_TURVO_STOP_UPDATE_FAILED,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    err,
                ),
                stop_name=name,
                start_time=wall_time,
                response=raw,
            )

        result = TurvoWriteResult(
            ok=True,
            updated=bool(raw.get("updated")),
            stop_name=name,
            start_time=wall_time,
            response=raw,
        )
        tid = str(tenant_id or "").strip()
        lid = str(load_id or "").strip()
        if tid and lid:
            override = str(customer_name_override or "").strip()
            if not override and payload is not None:
                override = str(delivery_stop_name_from_payload(payload) or "").strip()
            refresh = await ShipmentsService().refresh_display_from_turvo(
                tenant_id=tid,
                tenant_slug=slug,
                turvo_shipment_id=sid,
                load_id=lid,
                customer_name_override=override or None,
            )
            if not refresh.get("success"):
                logger.warning(
                    "shipment display refresh failed after turvo delivery update shipment_id=%s: %s",
                    sid,
                    refresh.get("message"),
                )
        return result

    def tender_from_state(self, state) -> TurvoWriteResult:
        return run_sync(self._tender_from_state_async(state))

    async def _tender_from_state_async(self, state) -> TurvoWriteResult:
        data = state.data or {}
        return await self.apply_tender(
            tenant_slug=str(data.get("tenant_slug") or "").strip(),
            shipment_id=str(data.get("shipment_id") or "").strip(),
            tenant_id=str(data.get("tenant_id") or "").strip(),
            load_id=str(data.get("load_id") or "").strip(),
            customer_name_override=str(data.get("customer_name") or "").strip() or None,
        )

    async def apply_tender(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        tenant_id: str = "",
        load_id: str = "",
        customer_name_override: str | None = None,
    ) -> TurvoWriteResult:
        slug = str(tenant_slug or "").strip()
        sid = str(shipment_id or "").strip()
        if not slug or not sid:
            wire = "missing_turvo_tender_fields"
            return TurvoWriteResult(
                ok=False,
                error=wire,
                failure=_wire_failure(wire, wire.replace("_", " ")),
            )

        try:
            payload = await fetch_app_shipment_details(slug, sid)
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo tender shipment fetch failed shipment_id=%s: %s",
                sid,
                exc,
            )
            return _turvo_fetch_failure(exc)

        if status_code_key_from_shipment_payload(payload) == TENDERED_STATUS_CODE_KEY:
            return TurvoWriteResult(ok=True, updated=False, skipped=True, response={"already_tendered": True})

        fragment_id = fragment_id_from_shipment_payload(payload)
        if not fragment_id:
            wire = "missing_fragment_id"
            return TurvoWriteResult(
                ok=False,
                error=wire,
                failure=_wire_failure(wire, wire.replace("_", " ")),
            )

        tz = timezone_from_shipment_payload(payload)
        body = build_tender_status_body(fragment_id=fragment_id, timezone=tz)

        try:
            raw = await update_shipment_tender_status(slug, sid, body)
        except (TurvoApiError, ValueError) as exc:
            logger.warning("turvo tender status PUT failed shipment_id=%s: %s", sid, exc)
            detail = str(exc)
            return TurvoWriteResult(
                ok=False,
                error=WIRE_TURVO_TENDER_STATUS_FAILED,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_TENDER_STATUS_FAILED,
                    detail,
                ),
            )

        tid = str(tenant_id or "").strip()
        lid = str(load_id or "").strip()
        if tid and lid:
            override = str(customer_name_override or "").strip() or None
            refresh = await ShipmentsService().refresh_display_from_turvo(
                tenant_id=tid,
                tenant_slug=slug,
                turvo_shipment_id=sid,
                load_id=lid,
                customer_name_override=override,
            )
            if not refresh.get("success"):
                logger.warning(
                    "shipment display refresh failed after turvo tender shipment_id=%s: %s",
                    sid,
                    refresh.get("message"),
                )

        return TurvoWriteResult(ok=True, updated=True, response=raw)


__all__ = ("AppointmentSchedulingTurvoWriteService", "TurvoWriteResult")
