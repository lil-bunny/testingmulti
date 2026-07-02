"""Tests for Turvo UI accounts contacts tab search (integrations)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.turvo.public_api_urls import build_turvo_ui_base_url
from app.integrations.turvo.ui_accounts import (
    driver_rows_from_contacts_tab,
    driver_rows_from_shipments,
    filter_driver_rows_by_name,
    filter_driver_rows_by_phone,
    search_carrier_driver_contacts_by_name,
    search_carrier_driver_contacts_by_phone,
)

_VIRAT_UI_ROW = {
    "contact_id": 640635,
    "name": "Virat",
    "phones": ["9989239823"],
}

_VIRAT_HYDRATED = {
    "id": 640635,
    "name": "Virat",
    "phones": ["9989239823"],
    "emails": ["virat.9823@freightx.local"],
    "raw": {"id": 640635, "name": "Virat"},
}

_WOLF_UI_ROW = {
    "contact_id": 604186,
    "name": "Alyssa Wolf",
    "phones": ["5122691730"],
}

_WOLF_HYDRATED = {
    "id": 604186,
    "name": "Alyssa Wolf",
    "phones": ["5122691730"],
    "emails": [],
    "raw": {"id": 604186, "name": "Alyssa Wolf"},
}


def _contacts_tab_payload(*basics: dict) -> dict:
    return {"contacts": {"data": [{"Basic": basic} for basic in basics]}}


def _shipments_payload(*drivers: dict) -> dict:
    return {
        "shipments": {
            "shipments": [
                {
                    "details": {
                        "carrier_orders": [
                            {
                                "carrier": {"id": 848297, "name": "Turvo Test Carrier"},
                                "drivers": list(drivers),
                            }
                        ]
                    }
                }
            ]
        }
    }


def _driver_basic(
    *,
    contact_id: int,
    full_name: str,
    phone: str,
) -> dict:
    return {
        "contactId": contact_id,
        "full_name": full_name,
        "roles": [{"key": "1993", "value": "Driver"}],
        "phones": [{"number": phone}],
    }


def test_build_turvo_ui_base_url_sandbox() -> None:
    assert (
        build_turvo_ui_base_url("https://my-sandbox-publicapi.turvo.com")
        == "https://my-sandbox.turvo.com"
    )


def test_driver_rows_from_shipments_extracts_phone() -> None:
    payload = _shipments_payload(
        {
            "context": {"id": 640635, "name": "Virat"},
            "phone": {"number": "9989239823"},
        }
    )
    rows = driver_rows_from_shipments(payload, carrier_id=848297)
    assert len(rows) == 1
    assert rows[0]["contact_id"] == 640635
    assert rows[0]["phone"] == "9989239823"


def test_driver_rows_from_contacts_tab_extracts_driver_phone() -> None:
    payload = _contacts_tab_payload(
        _driver_basic(contact_id=604186, full_name="Alyssa Wolf", phone="5122691730"),
        {
            "contactId": 999,
            "full_name": "Dispatcher",
            "roles": [{"key": "1000", "value": "Other"}],
            "phones": [{"number": "5122691730"}],
        },
    )
    rows = driver_rows_from_contacts_tab(payload)
    assert rows == [
        {
            "contact_id": 604186,
            "name": "Alyssa Wolf",
            "phones": ["5122691730"],
        }
    ]


def test_filter_driver_rows_by_phone_and_name() -> None:
    rows = [_VIRAT_UI_ROW, {"contact_id": 1, "name": "Other", "phones": ["1111111111"]}]
    assert filter_driver_rows_by_phone(rows, phone="9989239823", name="Virat") == [
        _VIRAT_UI_ROW
    ]
    assert filter_driver_rows_by_phone(rows, phone="9989239823", name="Anna") == []


def test_filter_driver_rows_by_name_partial_token() -> None:
    rows = [
        _WOLF_UI_ROW,
        {"contact_id": 1, "name": "Virat", "phones": ["9989239823"]},
    ]
    assert filter_driver_rows_by_name(rows, name="Alyssa") == [_WOLF_UI_ROW]
    assert filter_driver_rows_by_name(rows, name="Jonathan") == []


@pytest.mark.asyncio
async def test_search_by_name_finds_wolf_from_contacts_tab() -> None:
    payload = _contacts_tab_payload(
        _driver_basic(contact_id=604186, full_name="Alyssa Wolf", phone="5122691730"),
    )
    with (
        patch(
            "app.integrations.turvo.ui_accounts._fetch_ui_contacts_tab",
            new=AsyncMock(return_value=payload),
        ),
        patch(
            "app.integrations.turvo.ui_accounts.get_driver_contact",
            new=AsyncMock(return_value=_WOLF_HYDRATED),
        ),
    ):
        rows = await search_carrier_driver_contacts_by_name(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            name="Alyssa",
        )
    assert len(rows) == 1
    assert rows[0]["id"] == 604186
    assert rows[0]["name"] == "Alyssa Wolf"


@pytest.mark.asyncio
async def test_search_by_phone_finds_virat_from_contacts_tab() -> None:
    payload = _contacts_tab_payload(
        _driver_basic(contact_id=640635, full_name="Virat", phone="9989239823"),
    )
    with (
        patch(
            "app.integrations.turvo.ui_accounts._fetch_ui_contacts_tab",
            new=AsyncMock(return_value=payload),
        ),
        patch(
            "app.integrations.turvo.ui_accounts.get_driver_contact",
            new=AsyncMock(return_value=_VIRAT_HYDRATED),
        ),
    ):
        rows = await search_carrier_driver_contacts_by_phone(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="9989239823",
            name="Virat",
        )
    assert len(rows) == 1
    assert rows[0]["id"] == 640635


@pytest.mark.asyncio
async def test_search_by_phone_finds_wolf_not_in_shipment_history() -> None:
    payload = _contacts_tab_payload(
        _driver_basic(contact_id=604186, full_name="Alyssa Wolf", phone="5122691730"),
    )
    with (
        patch(
            "app.integrations.turvo.ui_accounts._fetch_ui_contacts_tab",
            new=AsyncMock(return_value=payload),
        ),
        patch(
            "app.integrations.turvo.ui_accounts.get_driver_contact",
            new=AsyncMock(return_value=_WOLF_HYDRATED),
        ),
    ):
        rows = await search_carrier_driver_contacts_by_phone(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="512-269-1730",
        )
    assert len(rows) == 1
    assert rows[0]["id"] == 604186
    assert rows[0]["name"] == "Alyssa Wolf"


@pytest.mark.asyncio
async def test_search_by_phone_no_match() -> None:
    payload = _contacts_tab_payload(
        _driver_basic(contact_id=640635, full_name="Virat", phone="9989239823"),
    )
    with patch(
        "app.integrations.turvo.ui_accounts._fetch_ui_contacts_tab",
        new=AsyncMock(return_value=payload),
    ):
        rows = await search_carrier_driver_contacts_by_phone(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="0000000000",
        )
    assert rows == []


@pytest.mark.asyncio
async def test_ui_request_uses_contacts_tab_on_carrier_account() -> None:
    oauth = MagicMock()
    oauth._load_tms.return_value = type(
        "Tms",
        (),
        {"public_api_url": "https://my-sandbox-publicapi.turvo.com", "ui_base_url": None},
    )()
    oauth.get_tenant_tokens = AsyncMock(return_value={"access_token": "tok"})

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _contacts_tab_payload(
        _driver_basic(contact_id=640635, full_name="Virat", phone="9989239823"),
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.integrations.turvo.ui_accounts.httpx.AsyncClient", return_value=mock_client),
        patch(
            "app.integrations.turvo.ui_accounts.get_driver_contact",
            new=AsyncMock(return_value=None),
        ),
    ):
        await search_carrier_driver_contacts_by_phone(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="9989239823",
            oauth=oauth,
        )

    called_url = mock_client.get.await_args.args[0]
    assert called_url.startswith("https://my-sandbox.turvo.com/api/accounts/848297")
    assert "contacts" in called_url
    assert "pageSize" in called_url


@pytest.mark.asyncio
async def test_ui_request_uses_explicit_ui_base_url_from_tenant_settings() -> None:
    oauth = MagicMock()
    oauth._load_tms.return_value = type(
        "Tms",
        (),
        {
            "public_api_url": "https://my-sandbox-publicapi.turvo.com",
            "ui_base_url": "https://app.turvo.com",
        },
    )()
    oauth.get_tenant_tokens = AsyncMock(return_value={"access_token": "tok"})

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _contacts_tab_payload(
        _driver_basic(contact_id=640635, full_name="Virat", phone="9989239823"),
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.integrations.turvo.ui_accounts.httpx.AsyncClient", return_value=mock_client),
        patch(
            "app.integrations.turvo.ui_accounts.get_driver_contact",
            new=AsyncMock(return_value=None),
        ),
    ):
        await search_carrier_driver_contacts_by_phone(
            "t3ra",
            carrier_id=848297,
            carrier_name="Turvo Test Carrier",
            phone="9989239823",
            oauth=oauth,
        )

    called_url = mock_client.get.await_args.args[0]
    assert called_url.startswith("https://app.turvo.com/api/accounts/848297")
