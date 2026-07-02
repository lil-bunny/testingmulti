"""Tests for Turvo contacts list pagination (integrations)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.turvo.contacts import (
    _paginate_carrier_driver_contacts,
    _paginate_contacts_list,
    list_carrier_driver_contacts,
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

_OTHER_CARRIER_DRIVER = {
    "id": 1,
    "name": "Other",
    "role": [{"key": "1993", "value": "Driver"}],
    "context": [{"id": "999", "name": "Other Carrier", "type": "CARRIER"}],
}

_NON_DRIVER_ON_CARRIER = {
    "id": 638947,
    "name": "Debdas",
    "role": [],
    "context": [
        {"id": "848297", "name": "Turvo Test Carrier", "type": "CARRIER"},
    ],
}


def _list_payload(*contacts: dict) -> dict:
    return {"details": {"contacts": list(contacts)}}


@pytest.mark.asyncio
async def test_paginate_contacts_list_omits_role_eq_param() -> None:
    client = AsyncMock()
    client.request = AsyncMock(return_value=_list_payload())
    await _paginate_contacts_list("t3ra", client=client)
    params = client.request.await_args.kwargs["params"]
    assert "role[eq]" not in params
    assert params["pageSize"] == "100"
    assert params["start"] == "0"


@pytest.mark.asyncio
async def test_list_carrier_driver_contacts_finds_driver_from_unfiltered_list() -> None:
    client = AsyncMock()
    client.request = AsyncMock(
        side_effect=[
            _list_payload(_VIRAT_RAW, _OTHER_CARRIER_DRIVER),
            {"details": {}},  # carrier embed empty
        ]
    )
    rows = await list_carrier_driver_contacts(
        "t3ra",
        carrier_id=848297,
        carrier_name="Turvo Test Carrier",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0]["id"] == 640635
    assert "role[eq]" not in client.request.await_args_list[0].kwargs["params"]


@pytest.mark.asyncio
async def test_list_carrier_driver_contacts_excludes_non_driver_on_carrier() -> None:
    client = AsyncMock()
    client.request = AsyncMock(
        return_value=_list_payload(_NON_DRIVER_ON_CARRIER, _VIRAT_RAW)
    )
    rows = await _paginate_carrier_driver_contacts(
        "t3ra",
        carrier_id=848297,
        carrier_name="Turvo Test Carrier",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0]["id"] == 640635
