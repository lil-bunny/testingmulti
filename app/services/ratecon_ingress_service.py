"""Pre-graph preparation for the ratecon workflow (Turvo resolve + shipment upsert)."""

from __future__ import annotations

from typing import Any

from app.services.shipments_service import ShipmentsService
from app.services.ratecon_supersede_service import RateconSupersedeService


class RateconIngressService:
    """Resolve Turvo load to shipment row before lifecycle correlation."""

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

    async def prepare_payload(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Require ``load_id``, resolve Turvo shipment, upsert ``shipments`` row.

        Sets ``shipment_id`` (Turvo number) and ``shipments_row_id`` (``shipments.id`` UUID).
        """
        load_id = self._clean(payload.get("load_id"))
        if not load_id:
            raise Exception(
                "Missing required payload keys for 'ratecon': ['load_id']"
            )

        persist = await self._shipments.upsert_from_load_id(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            load_id=load_id,
        )
        if not persist.get("success") or not persist.get("shipments_row_id"):
            message = persist.get("message") or "shipments_upsert_failed"
            if message == "turvo_load_resolve_failed":
                raise Exception(f"ratecon: Turvo load resolve failed: {message}")
            if message == "turvo_shipment_not_found":
                raise Exception(
                    "ratecon: Turvo load resolve failed: "
                    "No shipment found for load_id or could not extract shipment_id"
                )
            raise Exception(f"ratecon: shipment upsert failed: {message}")

        turvo_shipment_id = str(persist.get("shipment_number") or "").strip()
        out = dict(payload)
        out["shipment_id"] = turvo_shipment_id
        out["shipments_row_id"] = str(persist["shipments_row_id"])

        self._supersede.supersede_before_run(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            shipments_row_id=out["shipments_row_id"],
            load_id=load_id,
            shipment_id=turvo_shipment_id or None,
            communication_id=self._clean(payload.get("communication_id")),
        )

        return out
