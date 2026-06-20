"""Vendor-neutral workflow lifecycle cancel trigger (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SHIPMENT_TENDERED_TRIGGER = "shipment_tendered"
RATECON_SUPERSEDED_TRIGGER = "ratecon_superseded"


@dataclass(frozen=True)
class WorkflowCancelTrigger:
    trigger: str
    tenant_id: str
    tenant_slug: str
    shipment_number: str | None = None
    shipments_row_id: str | None = None
    load_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def shipment_correlation_error(self) -> str | None:
        if (self.shipment_number or "").strip():
            return None
        if (self.shipments_row_id or "").strip():
            return None
        return "missing_shipment_correlation"
