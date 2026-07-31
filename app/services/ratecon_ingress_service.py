"""Pre-graph preparation for the ratecon workflow (Turvo resolve + shipment upsert)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.error_catalog import BusinessError
from app.exceptions import WorkflowException
from app.integrations.turvo.load_to_shipment import load_id_to_shipment_id_async
from app.integrations.turvo.shipments import (
    get_shipment as get_turvo_shipment_async,
    is_multi_stop_shipment,
    shipment_workflow_state_projection,
)
from app.services.shipments_service import ShipmentsService
from app.services.ratecon_supersede_service import RateconSupersedeService

logger = get_logger(__name__)

RATECON_SKIP_MULTI_STOP = "multi_stop"
RATECON_SKIP_MISSING_LOAD_ID = "missing_load_id"


@dataclass(frozen=True)
class RateconIngressResult:
    """Outcome of ratecon pre-graph prepare (upsert or intentional skip)."""

    ok: bool
    payload: dict[str, Any] | None = None
    skip_reason: str | None = None


class RateconIngressService:
    """Resolve Turvo load/shipment, gate multi-stop, upsert before lifecycle."""

    def __init__(
        self,
        *,
        shipments_service: ShipmentsService | None = None,
        supersede_service: RateconSupersedeService | None = None,
    ) -> None:
        self._shipments = shipments_service or ShipmentsService()
        self._supersede = supersede_service or RateconSupersedeService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _custom_id_from_payload(turvo_payload: dict[str, Any]) -> str | None:
        details = turvo_payload.get("details")
        if not isinstance(details, dict):
            details = turvo_payload
        for key in ("customId", "custom_id"):
            raw = details.get(key) if isinstance(details, dict) else None
            if raw is None:
                continue
            s = str(raw).strip()
            if s:
                return s
        return None

    @staticmethod
    def _shipment_id_from_payload(turvo_payload: dict[str, Any]) -> str | None:
        details = turvo_payload.get("details")
        if isinstance(details, dict):
            raw = details.get("id")
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        raw = turvo_payload.get("id")
        if raw is not None and str(raw).strip():
            return str(raw).strip()
        return None

    async def _fetch_turvo_shipment(
        self,
        *,
        tenant_slug: str,
        shipment_id: str | None,
        load_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        """
        Resolve ``(turvo_shipment_id, turvo_payload)`` from shipment_id or load_id.

        Prefers a single get-by-id when ``shipment_id`` is known; otherwise
        load→shipment resolve then get. Raises on missing ids / Turvo failures.
        """
        slug = self._clean(tenant_slug)
        if not slug:
            raise Exception("ratecon: missing tenant_slug")

        sid = self._clean(shipment_id)
        if sid:
            try:
                turvo_payload = await get_turvo_shipment_async(slug, sid)
            except Exception as exc:
                logger.exception(
                    "ratecon Turvo get_shipment failed tenant_slug=%s shipment_id=%s",
                    slug,
                    sid,
                )
                raise Exception(
                    f"ratecon: Turvo get_shipment failed: {exc}"
                ) from exc
            if not isinstance(turvo_payload, dict):
                raise Exception("ratecon: invalid Turvo shipment payload")
            return sid, turvo_payload

        lid = self._clean(load_id)
        if not lid:
            raise Exception(
                "Missing required payload keys for 'ratecon': "
                "['load_id'] or ['shipment_id']"
            )

        try:
            resolved = await load_id_to_shipment_id_async(slug, lid)
        except Exception as exc:
            logger.exception(
                "ratecon Turvo load resolve failed tenant_slug=%s load_id=%s",
                slug,
                lid,
            )
            raise Exception(
                f"ratecon: Turvo load resolve failed: {exc}"
            ) from exc

        if not resolved:
            raise WorkflowException(BusinessError.SHIPMENT_NOT_FOUND_IN_TMS)

        sid = str(resolved).strip()
        try:
            turvo_payload = await get_turvo_shipment_async(slug, sid)
        except Exception as exc:
            logger.exception(
                "ratecon Turvo get_shipment failed tenant_slug=%s shipment_id=%s",
                slug,
                sid,
            )
            raise Exception(
                f"ratecon: Turvo get_shipment failed: {exc}"
            ) from exc
        if not isinstance(turvo_payload, dict):
            raise Exception("ratecon: invalid Turvo shipment payload")
        return sid, turvo_payload

    async def prepare_payload(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> RateconIngressResult:
        """
        Resolve Turvo shipment, gate multi-stop, upsert, then project for graph state.

        Flow: reuse projected ``shipment.details`` when present → else fetch →
        skip multi-stop → upsert + supersede when no ``shipments_row_id``.
        Outcomes: ``ok`` with ids and a checkpoint-safe ``shipment`` projection,
        or ``ok=False`` with ``skip_reason`` (no lifecycle enqueue).
        """
        load_id = self._clean(payload.get("load_id"))
        shipment_id = self._clean(payload.get("shipment_id"))
        existing_shipment = payload.get("shipment")

        # 1) Reuse stashed Turvo payload (e.g. email ingress prepared before enqueue).
        if isinstance(existing_shipment, dict) and existing_shipment.get("details") is not None:
            turvo_payload = existing_shipment
            turvo_shipment_id = (
                shipment_id
                or self._shipment_id_from_payload(turvo_payload)
                or ""
            )
            if not turvo_shipment_id:
                raise Exception("ratecon: stashed shipment missing id")
        else:
            if not load_id and not shipment_id:
                logger.info(
                    "ratecon ingress skipped missing_load_id tenant_slug=%s "
                    "thread_id=%s email_id=%s subject=%r",
                    tenant_slug,
                    payload.get("thread_id"),
                    payload.get("email_id"),
                    payload.get("subject"),
                )
                return RateconIngressResult(
                    ok=False,
                    payload=dict(payload),
                    skip_reason=RATECON_SKIP_MISSING_LOAD_ID,
                )
            turvo_shipment_id, turvo_payload = await self._fetch_turvo_shipment(
                tenant_slug=tenant_slug,
                shipment_id=shipment_id,
                load_id=load_id,
            )

        # NOTE: multi-stop gate disabled — ratecon graph is stop-agnostic
        # (upload + bookkeeping only). Will be removed once multi-stop is stable.
        # if is_multi_stop_shipment(turvo_payload):
        #     logger.info(
        #         "ratecon ingress skipped multi_stop tenant_slug=%s "
        #         "shipment_id=%s load_id=%s",
        #         tenant_slug,
        #         turvo_shipment_id,
        #         load_id,
        #     )
        #     skipped = dict(payload)
        #     skipped["shipment_id"] = turvo_shipment_id
        #     if load_id:
        #         skipped["load_id"] = load_id
        #     skipped["shipment"] = shipment_workflow_state_projection(turvo_payload)
        #     return RateconIngressResult(
        #         ok=False,
        #         payload=skipped,
        #         skip_reason=RATECON_SKIP_MULTI_STOP,
        #     )

        if not load_id:
            load_id = self._custom_id_from_payload(turvo_payload)
        if not load_id:
            raise Exception(
                "Missing required payload keys for 'ratecon': ['load_id'] "
                "(and Turvo payload has no customId)"
            )

        if not self._clean(shipment_id):
            from_payload = self._shipment_id_from_payload(turvo_payload)
            if from_payload:
                turvo_shipment_id = from_payload

        # 2) Upsert + supersede unless caller already has a shipments row.
        existing_row = self._clean(payload.get("shipments_row_id"))
        if existing_row:
            shipments_row_id = existing_row
            out_shipment_id = turvo_shipment_id
        else:
            persist = self._shipments.upsert_from_turvo(
                tenant_id=tenant_id,
                turvo_shipment_id=turvo_shipment_id,
                load_id=load_id,
                turvo_payload=turvo_payload,
            )
            if not persist.get("success") or not persist.get("shipments_row_id"):
                message = persist.get("message") or "shipments_upsert_failed"
                if message == "turvo_shipment_not_found":
                    raise WorkflowException(BusinessError.SHIPMENT_NOT_FOUND_IN_TMS)
                raise Exception(f"ratecon: shipment upsert failed: {message}")
            shipments_row_id = str(persist["shipments_row_id"])
            out_shipment_id = str(
                persist.get("shipment_number") or turvo_shipment_id
            ).strip()

            self._supersede.supersede_before_run(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                shipments_row_id=shipments_row_id,
                load_id=load_id,
                shipment_id=out_shipment_id or None,
                communication_id=self._clean(payload.get("communication_id")),
            )

        out = dict(payload)
        out["shipment_id"] = out_shipment_id
        out["shipments_row_id"] = shipments_row_id
        out["load_id"] = load_id
        out["shipment"] = shipment_workflow_state_projection(turvo_payload)

        return RateconIngressResult(ok=True, payload=out)
