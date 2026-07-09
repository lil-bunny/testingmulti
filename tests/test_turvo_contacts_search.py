"""Tests for Turvo carrier driver contact search (integrations)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.integrations.turvo.contacts import (
    search_carrier_driver_contacts,
)
from app.integrations.turvo.shipments import (
    driver_assignment_row_ids_from_carrier_order,
    driver_contact_ids_from_carrier_order,
    driver_contact_ids_from_shipment,
)

_VIRAT_RAW = {
    "id": 640635,
    "name": "Virat",
    "role": [{"key": "1993", "value": "Driver"}],
    "phone": [{"number": "9989239823"}],
    "context": [
        {"id": "848297", "name": "Turvo Test Carrier", "type": "CARRIER"},
    ],
}

_VIRAT_ROW = {
    "id": 640635,
    "name": "Virat",
    "phones": ["9989239823"],
    "emails": ["virat.9823@freightx.local"],
    "raw": _VIRAT_RAW,
}


def test_driver_contact_ids_from_carrier_order_collects_context_ids() -> None:
    order = {
        "deleted": False,
        "carrier": {"id": 848297, "name": "Turvo Test Carrier"},
        "drivers": [
            {"deleted": False, "context": {"id": 640635, "name": "Virat"}},
            {"deleted": True, "context": {"id": 999}},
            {"deleted": False, "driverId": 640637},
        ],
    }
    assert driver_contact_ids_from_carrier_order(order) == [640635, 640637]


def test_driver_assignment_row_ids_from_carrier_order() -> None:
    order = {
        "deleted": False,
        "drivers": [
            {"deleted": False, "id": "abc-1", "driverId": 640635},
            {"deleted": True, "id": "abc-2"},
        ],
    }
    assert driver_assignment_row_ids_from_carrier_order(order) == ["abc-1"]


def test_driver_contact_ids_from_shipment_scopes_to_carrier() -> None:
    payload = {
        "details": {
            "carrierOrder": [
                {
                    "deleted": False,
                    "carrier": {"id": 848297, "name": "Turvo Test Carrier"},
                    "drivers": [
                        {"deleted": False, "context": {"id": 640635, "name": "Virat"}},
                    ],
                }
            ]
        }
    }
    assert driver_contact_ids_from_shipment(payload, carrier_id=848297) == [640635]
    assert driver_contact_ids_from_shipment(payload, carrier_id=1) == []


def _list_payload(*contacts: dict) -> dict:
    return {"details": {"contacts": list(contacts)}}


_ANNA_RAW = {
    "id": 640636,
    "name": "anna",
    "role": [{"key": "1993", "value": "Driver"}],
    "phone": [{"number": "454235353"}],
    "context": [
        {"id": "848297", "name": "Turvo Test Carrier", "type": "CARRIER"},
    ],
}

_JOHN_SMITH_RAW = {
    "id": 640637,
    "name": "John Smith",
    "role": [{"key": "1993", "value": "Driver"}],
    "phone": [{"number": "9169170369"}],
    "context": [
        {"id": "848297", "name": "Turvo Test Carrier", "type": "CARRIER"},
    ],
}


@pytest.mark.asyncio
async def test_search_finds_virat_by_name_from_unfiltered_list() -> None:
    """Name search on carrier pool built from unfiltered /contacts/list (no shipment)."""
    client = AsyncMock()
    client.request = AsyncMock(
        side_effect=[
            _list_payload(_VIRAT_RAW, _ANNA_RAW),
            {"details": {}},  # carrier embed
        ]
    )
    matches = await search_carrier_driver_contacts(
        "t3ra",
        carrier_id=848297,
        carrier_name="Turvo Test Carrier",
        name="Virat",
        client=client,
    )
    assert len(matches) == 1
    assert matches[0]["id"] == 640635
    assert matches[0]["name"] == "Virat"
    list_params = client.request.await_args_list[0].kwargs["params"]
    assert "role[eq]" not in list_params


@pytest.mark.asyncio
async def test_search_finds_virat_when_list_empty_but_shipment_hydrates() -> None:
    shipment = {
        "details": {
            "carrierOrder": [
                {
                    "deleted": False,
                    "carrier": {"id": 848297, "name": "Turvo Test Carrier"},
                    "drivers": [
                        {"deleted": False, "context": {"id": 640635, "name": "Virat"}},
                    ],
                }
            ]
        }
    }
    with (
        patch(
            "app.integrations.turvo.contacts._paginate_carrier_driver_contacts",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.integrations.turvo.contacts._driver_contacts_from_carrier",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.integrations.turvo.contacts.get_driver_contact",
            new=AsyncMock(return_value=_VIRAT_ROW),
        ),
    ):
        matches = await search_carrier_driver_contacts(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            name="Virat",
            shipment_payload=shipment,
        )
    assert len(matches) == 1
    assert matches[0]["id"] == 640635


@pytest.mark.asyncio
async def test_search_finds_john_smith_by_first_name_token() -> None:
    with patch(
        "app.integrations.turvo.contacts.list_carrier_driver_contacts",
        new=AsyncMock(
            return_value=[
                {
                    "id": 640637,
                    "name": "John Smith",
                    "phones": ["9169170369"],
                    "emails": [],
                    "raw": _JOHN_SMITH_RAW,
                },
                {
                    "id": 640636,
                    "name": "anna",
                    "phones": ["454235353"],
                    "emails": [],
                    "raw": _ANNA_RAW,
                },
            ]
        ),
    ):
        matches = await search_carrier_driver_contacts(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            name="John",
        )
    assert len(matches) == 1
    assert matches[0]["name"] == "John Smith"


@pytest.mark.asyncio
async def test_search_phone_only_does_not_require_name_filter() -> None:
    with patch(
        "app.integrations.turvo.contacts.list_carrier_driver_contacts",
        new=AsyncMock(return_value=[_VIRAT_ROW]),
    ):
        matches = await search_carrier_driver_contacts(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="9989239823",
        )
    assert len(matches) == 1
    assert matches[0]["id"] == 640635
