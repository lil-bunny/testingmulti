"""Turvo stop appointment updates for appointment scheduling (placeholder + confirmed + tender)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.state_hygiene import (
    slim_turvo_write_result,
)
from app.domain.error_catalog import BusinessError, IntegrationError, format_error_message
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
    delivery_date_only_from_payload,
    delivery_stop_name_from_payload,
    get_shipment,
    update_stop_appointment_time,
)
from app.integrations.turvo.webhook_mapping import TENDERED_STATUS_CODE_KEY
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)
from app.services.shipments_service import ShipmentsService
from app.tools.appointment_scheduling.dates import prepare_delivery_placeholder

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

    def to_checkpoint_dict(self) -> dict[str, Any]:
        return slim_turvo_write_result(
            ok=self.ok,
            updated=self.updated,
            skipped=self.skipped,
            error=self.error,
            stop_name=self.stop_name,
            start_time=self.start_time,
        )


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
        return slim_turvo_write_result(
            ok=self.ok,
            updated=self.updated,
            error=self.error,
            stop_name=self.stop_name,
            start_time=self.start_time,
        )


def _vendor_error_message(raw: dict[str, Any], catalog: IntegrationError) -> str:
    return str(raw.get("error") or format_error_message(catalog))


@dataclass(frozen=True)
class TurvoStateContext:
    tenant_slug: str
    shipment_id: str
    tenant_id: str
    load_id: str
    customer_name: str | None
    shipment_payload: dict[str, Any] | None


def _turvo_context_from_data(data: dict[str, Any]) -> TurvoStateContext:
    payload = data.get("shipment") if isinstance(data.get("shipment"), dict) else None
    customer = str(data.get("customer_name") or "").strip()
    return TurvoStateContext(
        tenant_slug=str(data.get("tenant_slug") or "").strip(),
        shipment_id=str(data.get("shipment_id") or "").strip(),
        tenant_id=str(data.get("tenant_id") or "").strip(),
        load_id=str(data.get("load_id") or "").strip(),
        customer_name=customer or None,
        shipment_payload=payload,
    )


async def _fetch_shipment_payload(
    slug: str,
    sid: str,
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, SchedulingFailure | None]:
    if payload is not None:
        return payload, None
    try:
        return await get_shipment(slug, sid), None
    except (TurvoApiError, ValueError) as exc:
        logger.warning("turvo shipment fetch failed shipment_id=%s: %s", sid, exc)
        return None, SchedulingFailure.from_catalog(
            IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
            str(exc),
        )


class TurvoStopUpdateService:
    def __init__(
        self,
        *,
        activity_service: ActivityService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._activity = activity_service or ActivityService()
        self._shipments = shipments_service or ShipmentsService()

    def apply_delivery_placeholder_from_state(self, state) -> TurvoConfirmResult:
        result = run_sync(self._apply_delivery_placeholder_from_state_async(state))
        self._activity.record_turvo_confirm_placeholder(
            state,
            result=result.to_checkpoint_dict(),
        )
        return result

    async def _apply_delivery_placeholder_from_state_async(self, state) -> TurvoConfirmResult:
        ctx = _turvo_context_from_data(state.data or {})
        return await self.apply_delivery_placeholder(
            tenant_slug=ctx.tenant_slug,
            shipment_id=ctx.shipment_id,
            shipment_payload=ctx.shipment_payload,
        )

    async def apply_delivery_placeholder(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        shipment_payload: dict[str, Any] | None = None,
    ) -> TurvoConfirmResult:
        slug = tenant_slug
        sid = shipment_id
        if not slug or not sid:
            err = BusinessError.MISSING_TURVO_UPDATE_FIELDS
            return TurvoConfirmResult(
                ok=False,
                error=err.value,
                failure=SchedulingFailure.from_catalog(err),
            )

        payload, fetch_failure = await _fetch_shipment_payload(slug, sid, shipment_payload)
        if fetch_failure is not None:
            return TurvoConfirmResult(
                ok=False,
                error=IntegrationError.TURVO_SHIPMENT_FETCH_FAILED.value,
                failure=fetch_failure,
            )

        stop_name = str(delivery_stop_name_from_payload(payload or {}) or "").strip()
        delivery_date = delivery_date_only_from_payload(payload or {})
        placeholder = prepare_delivery_placeholder(
            stop_name=stop_name,
            delivery_date=str(delivery_date or ""),
        )
        if placeholder is None:
            err = BusinessError.MISSING_DELIVERY_STOP_OR_DATE
            return TurvoConfirmResult(
                ok=False,
                error=err.value,
                failure=SchedulingFailure.from_catalog(err),
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
                error=IntegrationError.TURVO_STOP_UPDATE_FAILED.value,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    detail,
                ),
                stop_name=placeholder.stop_name,
                start_time=placeholder.start_time,
            )

        ok = bool(raw.get("ok"))
        if not ok:
            catalog = IntegrationError.TURVO_STOP_UPDATE_FAILED
            err = _vendor_error_message(raw, catalog)
            return TurvoConfirmResult(
                ok=False,
                updated=bool(raw.get("updated")),
                error=catalog.value,
                failure=SchedulingFailure.from_catalog(catalog, err),
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

    def apply_delivery_from_state(self, state) -> TurvoWriteResult:
        result = run_sync(self._apply_delivery_from_state_async(state))
        self._activity.record_turvo_update(state)
        return result

    async def _apply_delivery_from_state_async(self, state) -> TurvoWriteResult:
        data = state.data or {}
        ctx = _turvo_context_from_data(data)
        extraction = data.get("customer_reply_extraction") or {}
        if not isinstance(extraction, dict):
            extraction = {}
        start_time = str(
            extraction.get("turvo_start_time") or data.get("confirmed_delivery_at") or ""
        ).strip()
        return await self.apply_delivery(
            tenant_slug=ctx.tenant_slug,
            shipment_id=ctx.shipment_id,
            start_time=start_time,
            shipment_payload=ctx.shipment_payload,
            tenant_id=ctx.tenant_id,
            load_id=ctx.load_id,
            customer_name_override=ctx.customer_name,
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
        slug = tenant_slug
        sid = shipment_id
        wall_time = start_time

        payload = shipment_payload if isinstance(shipment_payload, dict) else None
        if payload is None and slug and sid:
            fetched, fetch_failure = await _fetch_shipment_payload(slug, sid, None)
            if fetch_failure is not None:
                return TurvoWriteResult(
                    ok=False,
                    error=IntegrationError.TURVO_SHIPMENT_FETCH_FAILED.value,
                    failure=fetch_failure,
                )
            payload = fetched

        name = stop_name
        if not name and payload is not None:
            name = str(delivery_stop_name_from_payload(payload) or "").strip()

        if not slug or not sid or not name or not wall_time:
            err = BusinessError.MISSING_TURVO_UPDATE_FIELDS
            return TurvoWriteResult(
                ok=False,
                error=err.value,
                failure=SchedulingFailure.from_catalog(err),
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
            detail = str(exc)
            return TurvoWriteResult(
                ok=False,
                error=IntegrationError.TURVO_STOP_UPDATE_FAILED.value,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_STOP_UPDATE_FAILED,
                    detail,
                ),
                stop_name=name,
                start_time=wall_time,
            )

        ok = bool(raw.get("ok"))
        if not ok:
            catalog = IntegrationError.TURVO_STOP_UPDATE_FAILED
            err = _vendor_error_message(raw, catalog)
            return TurvoWriteResult(
                ok=False,
                updated=bool(raw.get("updated")),
                error=catalog.value,
                failure=SchedulingFailure.from_catalog(catalog, err),
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
        tid = tenant_id
        lid = load_id
        if tid and lid:
            override = customer_name_override
            if not override and payload is not None:
                override = str(delivery_stop_name_from_payload(payload) or "").strip() or None
            refresh = await self._shipments.refresh_display_from_turvo(
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

    def apply_turvo_tender_from_state(self, state) -> TurvoWriteResult:
        result = run_sync(self._apply_turvo_tender_from_state_async(state))
        if result.ok and (result.updated or result.skipped):
            self._activity.record_turvo_tendered(state)
        return result

    async def _apply_turvo_tender_from_state_async(self, state) -> TurvoWriteResult:
        ctx = _turvo_context_from_data(state.data or {})
        return await self.apply_tender(
            tenant_slug=ctx.tenant_slug,
            shipment_id=ctx.shipment_id,
            tenant_id=ctx.tenant_id,
            load_id=ctx.load_id,
            customer_name_override=ctx.customer_name,
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
        slug = tenant_slug
        sid = shipment_id
        if not slug or not sid:
            err = BusinessError.MISSING_TURVO_TENDER_FIELDS
            return TurvoWriteResult(
                ok=False,
                error=err.value,
                failure=SchedulingFailure.from_catalog(err),
            )

        try:
            payload = await fetch_app_shipment_details(slug, sid)
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "turvo tender shipment fetch failed shipment_id=%s: %s",
                sid,
                exc,
            )
            return TurvoWriteResult(
                ok=False,
                error=IntegrationError.TURVO_SHIPMENT_FETCH_FAILED.value,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_SHIPMENT_FETCH_FAILED,
                    str(exc),
                ),
            )

        if status_code_key_from_shipment_payload(payload) == TENDERED_STATUS_CODE_KEY:
            return TurvoWriteResult(ok=True, updated=False, skipped=True, response={"already_tendered": True})

        fragment_id = fragment_id_from_shipment_payload(payload)
        if not fragment_id:
            err = BusinessError.MISSING_TURVO_FRAGMENT_ID
            return TurvoWriteResult(
                ok=False,
                error=err.value,
                failure=SchedulingFailure.from_catalog(err),
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
                error=IntegrationError.TURVO_TENDER_STATUS_FAILED.value,
                failure=SchedulingFailure.from_catalog(
                    IntegrationError.TURVO_TENDER_STATUS_FAILED,
                    detail,
                ),
            )

        tid = tenant_id
        lid = load_id
        if tid and lid:
            refresh = await self._shipments.refresh_display_from_turvo(
                tenant_id=tid,
                tenant_slug=slug,
                turvo_shipment_id=sid,
                load_id=lid,
                customer_name_override=customer_name_override,
            )
            if not refresh.get("success"):
                logger.warning(
                    "shipment display refresh failed after turvo tender shipment_id=%s: %s",
                    sid,
                    refresh.get("message"),
                )

        return TurvoWriteResult(ok=True, updated=True, response=raw)


__all__ = (
    "TurvoStopUpdateService",
    "TurvoConfirmResult",
    "TurvoWriteResult",
)
