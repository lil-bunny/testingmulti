"""Resolve route-guide lanes and carrier emails from tender rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.db_repos import DbRepos
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.ingest_source_fields import source_liefmatch
from app.domain.routing_guide import (
    RoutingGuidePolicy,
    RoutingGuideRow,
    routing_guide_policy_for,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class RoutingGuideCarrierResolution:
    lane: RoutingGuideRow | None
    plan_carrier_name: str
    carrier_email: str
    lane_miss: bool
    missing_carrier_email: bool


def _delivery_postal_code(tender: dict[str, Any], *, policy: RoutingGuidePolicy) -> str:
    """Zip used for step-1 lane lookup from persisted tender delivery address."""
    delivery = tender.get("delivery_address")
    if not isinstance(delivery, dict):
        return ""
    return policy.normalize_lane_zip(delivery.get("postal_code"))


class RoutingGuideLookupService:
    def lookup_lane(
        self,
        *,
        tenant_id: str,
        tenant_slug: str | None,
        tender: dict[str, Any],
    ) -> RoutingGuideRow | None:
        """Zip-first lane match; partner disambiguation when multiple rows share a zip."""
        policy = routing_guide_policy_for(tenant_slug)
        if policy is None:
            return None

        zipcode = _delivery_postal_code(tender, policy=policy)
        if not zipcode:
            return None

        def _load(repos: DbRepos) -> list[RoutingGuideRow]:
            return repos.routing_guide.list_by_tenant_zipcode(
                tenant_id=tenant_id,
                zipcode=zipcode,
            )

        candidates = run_with_repos(_load)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        return policy.select_lane(
            candidates,
            source_partner_label=source_liefmatch(tender),
        )

    def resolve_carrier(
        self,
        *,
        tenant_id: str,
        tenant_slug: str | None,
        tender: dict[str, Any],
        attempt: int,
    ) -> RoutingGuideCarrierResolution:
        """Resolve plan carrier email for waterfall attempt; used by ``send_tender_email``."""
        policy = routing_guide_policy_for(tenant_slug)
        if policy is None:
            return RoutingGuideCarrierResolution(
                lane=None,
                plan_carrier_name="",
                carrier_email="",
                lane_miss=True,
                missing_carrier_email=False,
            )

        lane = self.lookup_lane(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tender=tender,
        )
        if lane is None:
            return RoutingGuideCarrierResolution(
                lane=None,
                plan_carrier_name="",
                carrier_email="",
                lane_miss=True,
                missing_carrier_email=False,
            )

        plan_name, carrier_email = policy.plan_carrier_for_attempt(
            lane.carriers,
            attempt,
        )
        if not plan_name or not carrier_email:
            logger.warning(
                "routing_guide missing carrier plan=%r attempt=%s guide_id=%s zip=%s tenant=%s",
                plan_name or None,
                attempt,
                lane.id,
                lane.zipcode,
                tenant_slug,
            )
            return RoutingGuideCarrierResolution(
                lane=lane,
                plan_carrier_name=plan_name,
                carrier_email="",
                lane_miss=False,
                missing_carrier_email=True,
            )

        return RoutingGuideCarrierResolution(
            lane=lane,
            plan_carrier_name=plan_name,
            carrier_email=carrier_email,
            lane_miss=False,
            missing_carrier_email=False,
        )
