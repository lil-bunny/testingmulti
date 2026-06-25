"""Unit tests for route-guide lookup service and policy registry."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.routing_guide import RoutingGuideRow, routing_guide_policy_for
from app.models.tenants import TenantSlug
from app.services.routing_guide_lookup_service import RoutingGuideLookupService
from app.tools.routing_guide_carrier import (
    build_carrier_note,
    build_carrier_note_from_resolution,
)


@patch("app.services.routing_guide_lookup_service.run_with_repos")
def test_lookup_service_unique_zip(mock_run: MagicMock) -> None:
    row = RoutingGuideRow(
        id="guide-1",
        customer_name="Melaleuca",
        zipcode="83402",
        metadata={},
        customer_aliases=[],
        carriers={"a": {"Schneider": "carrier@example.com"}},
    )
    mock_run.return_value = [row]

    service = RoutingGuideLookupService()
    lane = service.lookup_lane(
        tenant_id="tenant-1",
        tenant_slug=TenantSlug.GELITA,
        tender={"delivery_address": {"postal_code": "83402"}},
    )
    assert lane == row


@patch("app.services.routing_guide_lookup_service.run_with_repos")
def test_resolve_carrier_uses_row_carriers(mock_run: MagicMock) -> None:
    row = RoutingGuideRow(
        id="guide-1",
        customer_name="Melaleuca",
        zipcode="83402",
        metadata={},
        customer_aliases=[],
        carriers={"a": {"Schneider": "lane@schneider.example"}},
    )
    mock_run.return_value = [row]

    service = RoutingGuideLookupService()
    resolution = service.resolve_carrier(
        tenant_id="tenant-1",
        tenant_slug=TenantSlug.GELITA,
        tender={"delivery_address": {"postal_code": "83402"}},
        attempt=1,
    )
    assert resolution.carrier_email == "lane@schneider.example"
    assert resolution.plan_carrier_name == "Schneider"
    assert resolution.missing_carrier_email is False


@patch("app.services.routing_guide_lookup_service.run_with_repos")
def test_resolve_carrier_lane_miss(mock_run: MagicMock) -> None:
    mock_run.return_value = []
    service = RoutingGuideLookupService()
    resolution = service.resolve_carrier(
        tenant_id="tenant-1",
        tenant_slug=TenantSlug.GELITA,
        tender={"delivery_address": {"postal_code": "83402"}},
        attempt=1,
    )
    assert resolution.lane_miss is True
    note = build_carrier_note_from_resolution(attempt=1, resolution=resolution)
    assert "Route guide lane not found" in note


def test_resolve_carrier_unknown_tenant_fails_closed() -> None:
    service = RoutingGuideLookupService()
    resolution = service.resolve_carrier(
        tenant_id="tenant-1",
        tenant_slug=TenantSlug.T3RA,
        tender={"delivery_address": {"postal_code": "83402"}},
        attempt=1,
    )
    assert resolution.lane_miss is True


def test_routing_guide_policy_registry() -> None:
    assert routing_guide_policy_for(TenantSlug.GELITA) is not None
    assert routing_guide_policy_for(TenantSlug.T3RA) is None
    assert routing_guide_policy_for(None) is None


def test_build_carrier_note_attempts() -> None:
    email = "carrier@example.com"
    assert build_carrier_note(1, email) == f"Note: Use carrier {email}"
    assert "Carrier 1 did not respond" in build_carrier_note(2, email)
