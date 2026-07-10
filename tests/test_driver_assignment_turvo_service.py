"""Tests for DriverAssignmentTurvoService decision matrix."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.driver_assignment.turvo_service import (
    DriverAssignmentTurvoService,
    TmsDriverResolution,
)


def _shipment(*, carrier_id=848297, carrier_name="Test Carrier", order_id=653902, customer_name="DIAMOND PET FOODS"):
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"id": 1, "name": customer_name},
                }
            ],
            "carrierOrder": [
                {
                    "deleted": False,
                    "id": order_id,
                    "carrier": {"id": carrier_id, "name": carrier_name},
                    "segmentId": "seg-1",
                }
            ]
        }
    }


def _virat_match():
    return {
        "id": 640635,
        "name": "Virat",
        "phones": ["9989239823"],
        "emails": [],
        "raw": {
            "id": 640635,
            "name": "Virat",
            "context": [{"id": "848297", "type": "CARRIER"}],
        },
    }


@pytest.mark.asyncio
async def test_name_only_single_match_assigns() -> None:
    svc = DriverAssignmentTurvoService()
    search_mock = AsyncMock(return_value=[{"id": 99, "phones": [], "emails": [], "raw": {"context": [{"id": "848297", "type": "CARRIER"}]}}])
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            search_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            new=AsyncMock(return_value={"Status": "SUCCESS"}),
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "anna", "phone": None, "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_contact_id == 99
    assert search_mock.await_args.kwargs.get("shipment_payload") is not None


@pytest.mark.asyncio
async def test_name_only_finds_virat_via_search_when_list_empty() -> None:
    svc = DriverAssignmentTurvoService()
    search_mock = AsyncMock(return_value=[_virat_match()])
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    shipment = _shipment(carrier_name="Turvo Test Carrier")
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=shipment),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            search_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Virat", "phone": None, "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_contact_id == 640635
    assert result.tms_matched_driver_name == "Virat"
    assert result.tms_matched_driver_phone == "9989239823"
    assert search_mock.await_args.kwargs["name"] == "Virat"
    assert search_mock.await_args.kwargs["shipment_payload"] == shipment


def test_resolve_from_state_merges_turvo_phone_into_extraction() -> None:
    svc = DriverAssignmentTurvoService()
    resolution = TmsDriverResolution(
        outcome="assigned",
        tms_resolution="found",
        tms_contact_id=640635,
        tms_matched_driver_name="Virat",
        tms_matched_driver_phone="9989239823",
    )
    state = SimpleNamespace(
        data={
            "tenant_slug": "t3ra",
            "shipment_id": "1000324895",
            "driver_details_extraction": {
                "driver": {"name": "Virat", "phone": None, "email": None},
            },
        }
    )
    with patch.object(
        svc,
        "resolve_and_assign",
        new=AsyncMock(return_value=resolution),
    ):
        state_patch = svc.resolve_from_state(state)
    assert state_patch["tms_matched_driver_phone"] == "9989239823"
    assert state_patch["driver_details_extraction"]["driver"]["phone"] == "9989239823"
    assert state_patch["driver_details_extraction"]["driver"]["name"] == "Virat"


@pytest.mark.asyncio
async def test_phone_only_not_found_follow_up() -> None:
    svc = DriverAssignmentTurvoService()
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": None, "phone": "+1454235353", "email": None},
        )
    assert result.outcome == "follow_up"
    assert result.tms_resolution == "not_found"
    assert result.tms_follow_up_reason == "not_found"


@pytest.mark.asyncio
async def test_name_and_phone_not_found_creates_and_assigns() -> None:
    svc = DriverAssignmentTurvoService()
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.create_driver_contact",
            new=AsyncMock(return_value=640535),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            new=AsyncMock(return_value={"Status": "SUCCESS"}),
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "anna", "phone": "454235353", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "created"
    assert result.tms_contact_id == 640535
    assert result.tms_contact_created is True


@pytest.mark.asyncio
async def test_non_uscs_customer_send_invite_true() -> None:
    svc = DriverAssignmentTurvoService()
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment(customer_name="DIAMOND PET FOODS")),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            new=AsyncMock(return_value=[{"id": 99, "phones": [], "emails": [], "raw": {"context": [{"id": "848297", "type": "CARRIER"}]}}]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "anna", "phone": None, "email": None},
        )
    assign_mock.assert_awaited_once()
    assert assign_mock.await_args.kwargs["send_invite"] is True
    assert result.tms_is_tracking_customer is False
    state_patch = result.to_state_patch()
    assert state_patch.get("tms_is_tracking_customer") is not True


@pytest.mark.asyncio
async def test_uscs_customer_send_invite_false() -> None:
    svc = DriverAssignmentTurvoService()
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment(customer_name="USCS CSC")),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            new=AsyncMock(return_value=[{"id": 99, "phones": [], "emails": [], "raw": {"context": [{"id": "848297", "type": "CARRIER"}]}}]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "anna", "phone": None, "email": None},
            tenant_settings={
                "driver_assignment": {
                    "confirmation_email": {
                        "tracking_customer_names": ["USCS CSC"],
                        "send_invite_for_tracking": False,
                    }
                }
            },
        )
    assert assign_mock.await_args.kwargs["send_invite"] is False
    assert result.tms_is_tracking_customer is True
    assert result.to_state_patch()["tms_is_tracking_customer"] is True


def _john_smith_match(*, contact_id: int = 640636, phone: str = "9169170369") -> dict:
    return {
        "id": contact_id,
        "name": "John Smith",
        "phones": [phone],
        "emails": [],
        "raw": {
            "id": contact_id,
            "name": "John Smith",
            "context": [{"id": "848297", "type": "CARRIER"}],
        },
    }


def _alyssa_duplicate_matches(*, phone: str = "512-269-1730") -> list[dict]:
    return [
        {
            "id": 640680,
            "name": "Alyssa",
            "phones": [phone],
            "emails": [],
            "raw": {"id": 640680, "name": "Alyssa"},
        },
        {
            "id": 604186,
            "name": "Alyssa Wolf",
            "phones": [phone],
            "emails": [],
            "raw": {"id": 604186, "name": "Alyssa Wolf"},
        },
    ]


@pytest.mark.asyncio
async def test_phone_partial_name_single_hit_assigns() -> None:
    svc = DriverAssignmentTurvoService()
    phone_mock = AsyncMock(return_value=[_john_smith_match()])
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            phone_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "John", "phone": "9169170369", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_contact_id == 640636
    assert result.tms_matched_driver_name == "John Smith"
    assert phone_mock.await_args.kwargs["name"] is None
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_phone_multiple_hits_same_first_name_ambiguous() -> None:
    svc = DriverAssignmentTurvoService()
    john_williams = _john_smith_match(contact_id=640637)
    john_williams["name"] = "John Williams"
    john_williams["raw"]["name"] = "John Williams"
    phone_mock = AsyncMock(
        return_value=[
            _john_smith_match(contact_id=640636),
            john_williams,
        ]
    )
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            phone_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "John", "phone": "9169170369", "email": None},
        )
    assert result.outcome == "follow_up"
    assert result.tms_resolution == "ambiguous"
    assert result.tms_follow_up_reason == "multiple_matches"
    assert result.tms_match_count == 2


@pytest.mark.asyncio
async def test_phone_duplicate_nested_names_picks_richest() -> None:
    svc = DriverAssignmentTurvoService()
    phone_mock = AsyncMock(return_value=_alyssa_duplicate_matches())
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            phone_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Alyssa", "phone": "512-269-1730", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_contact_id == 604186
    assert result.tms_matched_driver_name == "Alyssa Wolf"
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_phone_duplicate_no_name_picks_nested() -> None:
    svc = DriverAssignmentTurvoService()
    phone_mock = AsyncMock(return_value=_alyssa_duplicate_matches())
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            phone_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": None, "phone": "512-269-1730", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_contact_id == 604186
    assert result.tms_matched_driver_name == "Alyssa Wolf"
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_phone_hit_name_mismatch_not_found_no_create() -> None:
    svc = DriverAssignmentTurvoService()
    jane = _john_smith_match(contact_id=640638)
    jane["name"] = "Jane Doe"
    jane["raw"]["name"] = "Jane Doe"
    phone_mock = AsyncMock(
        return_value=[_john_smith_match(contact_id=640636), jane]
    )
    create_mock = AsyncMock(return_value=999)
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            phone_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.create_driver_contact",
            create_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Jonathan", "phone": "9169170369", "email": None},
        )
    assert result.outcome == "follow_up"
    assert result.tms_resolution == "not_found"
    create_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_name_only_partial_token_match_assigns() -> None:
    svc = DriverAssignmentTurvoService()
    search_mock = AsyncMock(return_value=[_john_smith_match()])
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            search_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "John", "phone": None, "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_matched_driver_name == "John Smith"
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_name_only_fallback_contacts_tab_finds_wolf() -> None:
    svc = DriverAssignmentTurvoService()
    wolf = {
        "id": 604186,
        "name": "Alyssa Wolf",
        "phones": ["5122691730"],
        "emails": [],
        "raw": {"id": 604186, "name": "Alyssa Wolf"},
    }
    pub_mock = AsyncMock(return_value=[])
    ui_name_mock = AsyncMock(return_value=[wolf])
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            pub_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_name",
            ui_name_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Alyssa", "phone": None, "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "found"
    assert result.tms_contact_id == 604186
    assert result.tms_matched_driver_name == "Alyssa Wolf"
    ui_name_mock.assert_awaited_once()
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_name_only_fallback_ambiguous_two_matches() -> None:
    svc = DriverAssignmentTurvoService()
    john_williams = _john_smith_match(contact_id=640637)
    john_williams["name"] = "John Williams"
    john_williams["raw"]["name"] = "John Williams"
    pub_mock = AsyncMock(return_value=[])
    ui_name_mock = AsyncMock(
        return_value=[_john_smith_match(contact_id=640636), john_williams]
    )
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            pub_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_name",
            ui_name_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "John", "phone": None, "email": None},
        )
    assert result.outcome == "follow_up"
    assert result.tms_resolution == "ambiguous"
    assert result.tms_follow_up_reason == "multiple_matches"
    assert result.tms_match_count == 2


@pytest.mark.asyncio
async def test_name_only_skips_fallback_when_public_api_hits() -> None:
    svc = DriverAssignmentTurvoService()
    pub_mock = AsyncMock(return_value=[_john_smith_match()])
    ui_name_mock = AsyncMock(return_value=[])
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts",
            pub_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_name",
            ui_name_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "John", "phone": None, "email": None},
        )
    assert result.outcome == "assigned"
    ui_name_mock.assert_not_awaited()
    assign_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_shadow_mode_skips_assign_driver_to_shipment() -> None:
    svc = DriverAssignmentTurvoService()
    assign_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    create_mock = AsyncMock(return_value=640635)
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment()),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.driver_assigned_from_payload",
            return_value=False,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            new=AsyncMock(return_value=[_virat_match()]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.create_driver_contact",
            create_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Virat", "phone": "9989239823", "email": None},
            tenant_settings={"driver_assignment": {"shadow_mode": True}},
            state_data={"workflow_shadow_mode": True},
        )
    assert result.outcome == "assigned"
    assert result.tms_contact_id == 640635
    assign_mock.assert_not_awaited()
    create_mock.assert_not_awaited()


def _shipment_with_driver(*, driver_contact_id=640635, row_id="row-1", order_id=653902):
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"id": 1, "name": "DIAMOND PET FOODS"},
                }
            ],
            "carrierOrder": [
                {
                    "deleted": False,
                    "id": order_id,
                    "carrier": {"id": 848297, "name": "Test Carrier"},
                    "segmentId": "seg-1",
                    "drivers": [
                        {
                            "deleted": False,
                            "id": row_id,
                            "context": {"id": driver_contact_id, "name": "Old Driver"},
                        }
                    ],
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_same_contact_on_shipment_skips_assign_and_replace() -> None:
    svc = DriverAssignmentTurvoService()
    assign_mock = AsyncMock()
    replace_mock = AsyncMock()
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment_with_driver(driver_contact_id=640635)),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            new=AsyncMock(return_value=[_virat_match()]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.assign_driver_to_shipment",
            assign_mock,
        ),
        patch(
            "app.services.driver_assignment.turvo_service.replace_driver_on_shipment",
            replace_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Virat", "phone": "9989239823", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "skipped_already_assigned"
    assert result.tms_contact_id == 640635
    assign_mock.assert_not_awaited()
    replace_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_different_contact_on_shipment_calls_replace() -> None:
    svc = DriverAssignmentTurvoService()
    replace_mock = AsyncMock(return_value={"Status": "SUCCESS"})
    other_match = {
        "id": 640637,
        "name": "Other",
        "phones": ["5122691730"],
        "emails": [],
        "raw": {
            "id": 640637,
            "name": "Other",
            "context": [{"id": "848297", "type": "CARRIER"}],
        },
    }
    with (
        patch(
            "app.services.driver_assignment.turvo_service.get_shipment",
            new=AsyncMock(return_value=_shipment_with_driver(driver_contact_id=640635)),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.search_carrier_driver_contacts_by_phone",
            new=AsyncMock(return_value=[other_match]),
        ),
        patch(
            "app.services.driver_assignment.turvo_service.replace_driver_on_shipment",
            replace_mock,
        ),
    ):
        result = await svc.resolve_and_assign(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            driver={"name": "Other", "phone": "5122691730", "email": None},
        )
    assert result.outcome == "assigned"
    assert result.tms_resolution == "replaced"
    assert result.tms_contact_id == 640637
    replace_mock.assert_awaited_once()
    kwargs = replace_mock.await_args.kwargs
    assert kwargs["assignment_row_ids"] == ["row-1"]
    assert kwargs["contact_id"] == 640637
