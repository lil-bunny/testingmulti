"""Tenant routing-guide policy registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TYPE_CHECKING

from app.domain.gelita import routing_guide as gelita_routing_guide
from app.models.tenants import TenantSlug

if TYPE_CHECKING:
    from app.domain.routing_guide.types import PlanCarriers, RoutingGuideRow


class RoutingGuidePolicy(Protocol):
    tenant_slug: str

    def normalize_lane_zip(self, value: Any) -> str: ...

    def select_lane(
        self,
        candidates: list[RoutingGuideRow],
        *,
        source_partner_label: str,
    ) -> RoutingGuideRow | None: ...

    def plan_carrier_for_attempt(
        self,
        carriers: PlanCarriers,
        attempt: int,
    ) -> tuple[str, str]: ...


@dataclass(frozen=True)
class _GelitaRoutingGuidePolicy:
    tenant_slug: str = TenantSlug.GELITA

    def normalize_lane_zip(self, value: Any) -> str:
        return gelita_routing_guide.gelita_normalize_lane_zip(value)

    def select_lane(
        self,
        candidates: list[RoutingGuideRow],
        *,
        source_partner_label: str,
    ) -> RoutingGuideRow | None:
        return gelita_routing_guide.gelita_select_lane(
            candidates,
            source_partner_label=source_partner_label,
        )

    def plan_carrier_for_attempt(
        self,
        carriers: PlanCarriers,
        attempt: int,
    ) -> tuple[str, str]:
        return gelita_routing_guide.gelita_plan_carrier_for_attempt(
            carriers,
            attempt,
        )


_GELITA_ROUTING_GUIDE_POLICY = _GelitaRoutingGuidePolicy()

_ROUTING_GUIDE_POLICIES: dict[str, RoutingGuidePolicy] = {
    TenantSlug.GELITA: _GELITA_ROUTING_GUIDE_POLICY,
}


def routing_guide_policy_for(tenant_slug: str | None) -> RoutingGuidePolicy | None:
    """Return lane lookup policy for a tenant slug, or ``None`` when unsupported."""
    return _ROUTING_GUIDE_POLICIES.get((tenant_slug or "").strip().lower())
