"""Pre-graph preparation for the ratecon workflow (Turvo resolve + shipment upsert)."""

from __future__ import annotations

from typing import Any

from app.integrations.turvo.load_to_shipment import load_id_to_shipment_id_async
from app.services.shipments_service import ShipmentsService


class RateconIngressService:
    """Resolve Turvo load to shipment row before lifecycle correlation."""

    def __init__(self, *, shipments_service: ShipmentsService | None = None) -> None:
        self._shipments = shipments_service or ShipmentsService()

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

        try:
            turvo_shipment_id = await load_id_to_shipment_id_async(
                tenant_slug, load_id
            )
        except Exception as exc:
            raise Exception(
                f"ratecon: Turvo load resolve failed: {exc}"
            ) from exc

        if not turvo_shipment_id:
            raise Exception(
                "ratecon: Turvo load resolve failed: "
                "No shipment found for load_id or could not extract shipment_id"
            )

        turvo_shipment_id = str(turvo_shipment_id).strip()
        persist = self._shipments.upsert_from_turvo(
            tenant_id=tenant_id,
            turvo_shipment_id=turvo_shipment_id,
            load_id=load_id,
        )
        if not persist.get("success") or not persist.get("shipments_row_id"):
            message = persist.get("message") or "shipments_upsert_failed"
            raise Exception(f"ratecon: shipment upsert failed: {message}")

        out = dict(payload)
        out["shipment_id"] = turvo_shipment_id
        out["shipments_row_id"] = str(persist["shipments_row_id"])
        return out
