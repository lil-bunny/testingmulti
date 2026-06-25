"""Routing-guide carrier note helpers; delegates lane lookup to ``RoutingGuideLookupService``."""

from __future__ import annotations

from html import escape
from typing import Any

from app.services.routing_guide_lookup_service import (
    RoutingGuideCarrierResolution,
    RoutingGuideLookupService,
)

_MISSING_CARRIER_NOTE_STYLE = "color: red; font-style: italic;"


def build_carrier_note(attempt: int, email: str) -> str:
    """Format carrier note line for tender email template."""
    addr = str(email or "").strip()
    if not addr:
        return _highlight_carrier_note("Carrier email missing")
    if attempt <= 1:
        return f"Note: Use carrier {addr}"
    prior = attempt - 1
    return f"Carrier {prior} did not respond, please send to {addr}"


def _highlight_carrier_note(text: str) -> str:
    return f'<span style="{_MISSING_CARRIER_NOTE_STYLE}">{escape(text)}</span>'


def resolve_carrier_for_tender(
    *,
    tenant_id: str,
    tenant_slug: str | None,
    tender: dict[str, Any],
    attempt: int,
) -> RoutingGuideCarrierResolution:
    """Entry point from ``send_tender_email`` for per-attempt carrier resolution."""
    routing_guide_lookup_service = RoutingGuideLookupService()
    return routing_guide_lookup_service.resolve_carrier(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        tender=tender,
        attempt=attempt,
    )


def build_carrier_note_from_resolution(
    *,
    attempt: int,
    resolution: RoutingGuideCarrierResolution,
) -> str:
    """Build HTML carrier note including business-gap highlighting."""
    if resolution.lane_miss:
        return _highlight_carrier_note("Route guide lane not found")
    if resolution.missing_carrier_email:
        label = resolution.plan_carrier_name or f"attempt {attempt}"
        return _highlight_carrier_note(f"Carrier email missing for {label}")
    return build_carrier_note(attempt, resolution.carrier_email)
