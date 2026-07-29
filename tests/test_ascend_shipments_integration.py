"""Tests for Ascend shipment HTTP helpers."""

from __future__ import annotations

from unittest.mock import patch

import httpx

from app.integrations.ascend.shipments import update_shipment_stops


def test_update_shipment_stops_empty_success_body_returns_empty_dict() -> None:
    response = httpx.Response(200, content=b"")

    with patch("app.integrations.ascend.shipments.httpx.put", return_value=response):
        result = update_shipment_stops(
            reference_number="DIAMOND-RPN00008996",
            access_token="token",
            office_code="DIAMOND-RPN",
            payload={"shipmentStops": []},
        )

    assert result == {}


def test_update_shipment_stops_non_json_success_body_returns_empty_dict() -> None:
    response = httpx.Response(200, content=b"OK")

    with patch("app.integrations.ascend.shipments.httpx.put", return_value=response):
        result = update_shipment_stops(
            reference_number="DIAMOND-RPN00008996",
            access_token="token",
            office_code="DIAMOND-RPN",
            payload={"shipmentStops": []},
        )

    assert result == {}
