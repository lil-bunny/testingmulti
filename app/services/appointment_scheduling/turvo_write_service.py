"""Turvo delivery appointment write for appointment scheduling replies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    delivery_stop_name_from_payload,
    get_shipment,
    update_stop_appointment_time,
)
from app.services.shipments_service import ShipmentsService

logger = get_logger(__name__)


@dataclass(frozen=True)
class TurvoWriteResult:
    ok: bool
    updated: bool = False
    error: str | None = None
    stop_name: str | None = None
    start_time: str | None = None
    response: dict[str, Any] | None = None


class AppointmentSchedulingTurvoWriteService:
    async def apply_delivery_from_state(self, state) -> TurvoWriteResult:
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
                return TurvoWriteResult(ok=False, error=str(exc))

        name = str(stop_name or "").strip()
        if not name and payload is not None:
            name = str(delivery_stop_name_from_payload(payload) or "").strip()

        if not slug or not sid or not name or not wall_time:
            return TurvoWriteResult(ok=False, error="missing_turvo_update_fields")

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
            return TurvoWriteResult(ok=False, error=str(exc), stop_name=name, start_time=wall_time)

        ok = bool(raw.get("ok"))
        result = TurvoWriteResult(
            ok=ok,
            updated=bool(raw.get("updated")),
            error=str(raw.get("error") or "") or None,
            stop_name=name,
            start_time=wall_time,
            response=raw,
        )
        tid = str(tenant_id or "").strip()
        lid = str(load_id or "").strip()
        if ok and tid and lid:
            refresh = await ShipmentsService().refresh_display_from_turvo(
                tenant_id=tid,
                tenant_slug=slug,
                turvo_shipment_id=sid,
                load_id=lid,
            )
            if not refresh.get("success"):
                logger.warning(
                    "shipment display refresh failed after turvo delivery update shipment_id=%s: %s",
                    sid,
                    refresh.get("message"),
                )
        return result


__all__ = ("AppointmentSchedulingTurvoWriteService", "TurvoWriteResult")
