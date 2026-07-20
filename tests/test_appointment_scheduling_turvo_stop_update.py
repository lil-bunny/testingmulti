"""Unit tests for Turvo update_stop_appointment_time."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.turvo.shipments import (
    delivery_stop_name_from_payload,
    update_stop_appointment_time,
)


def _shipment(*, stop_name: str = "Costco Depot") -> dict:
    return {
        "details": {
            "globalRoute": [
                {
                    "deleted": False,
                    "id": 101,
                    "name": "Ripon Pickup",
                    "appointment": {"date": "2026-07-01T12:00:00Z", "timeZone": "America/Los_Angeles"},
                },
                {
                    "deleted": False,
                    "id": 202,
                    "name": stop_name,
                    "appointment": {"date": "2026-07-10T15:00:00Z", "timeZone": "America/Los_Angeles"},
                },
            ]
        }
    }


@pytest.mark.asyncio
async def test_update_stop_appointment_time_puts_global_route() -> None:
    client = MagicMock()
    client.request = AsyncMock(return_value={"respMsg": "SUCCESS_UPDATE"})
    result = await update_stop_appointment_time(
        "t3ra",
        "1000324895",
        stop_name="Costco Depot",
        start_time="2026-07-18 10:30:00",
        shipment_payload=_shipment(),
        client=client,
    )
    assert result["ok"] is True
    assert result["updated"] is True
    client.request.assert_called_once()
    body = client.request.call_args.kwargs["json_body"]
    assert body["globalRoute"][0]["id"] == 202
    assert body["globalRoute"][0]["appointment"]["timeZone"] == "America/Los_Angeles"


@pytest.mark.asyncio
async def test_update_stop_not_found() -> None:
    result = await update_stop_appointment_time(
        "t3ra",
        "1001",
        stop_name="Missing Stop",
        start_time="2026-07-18 10:30:00",
        shipment_payload=_shipment(stop_name="Other"),
    )
    assert result["ok"] is False
    assert result["error"] == "stop_not_found"


def test_delivery_stop_name_from_customer_order_delivery_location() -> None:
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "items": [
                        {
                            "deliveryLocation": [{"name": "Costco Depot SC"}],
                        }
                    ],
                }
            ],
            "globalRoute": [
                {"deleted": False, "name": "Wrong Stop Name"},
            ],
        }
    }
    assert delivery_stop_name_from_payload(payload) == "Costco Depot SC"


def test_delivery_stop_name_falls_back_to_last_global_route_stop() -> None:
    assert delivery_stop_name_from_payload(_shipment(stop_name="Costco Depot")) == "Costco Depot"


def test_delivery_stop_name_from_empty_payload() -> None:
    assert delivery_stop_name_from_payload({}) is None
