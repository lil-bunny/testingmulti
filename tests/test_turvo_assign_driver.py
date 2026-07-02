"""Tests for Turvo shipment driver assignment payload."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.turvo.shipments import (
    DRIVER_TYPE_SINGLE,
    TRACKING_METHOD_NONE,
    TRACKING_METHOD_TURVO_APP,
    assign_driver_to_shipment,
)


@pytest.mark.asyncio
async def test_assign_driver_send_invite_uses_turvo_app_and_single_driver_type() -> None:
    client = AsyncMock()
    client.request = AsyncMock(return_value={"Status": "SUCCESS"})
    await assign_driver_to_shipment(
        "t3ra",
        "1000324895",
        carrier_order_id=653902,
        contact_id=640637,
        segment_id="seg-1",
        send_invite=True,
        client=client,
    )
    body = client.request.await_args.kwargs["json_body"]
    driver = body["carrierOrder"][0]["drivers"][0]
    assert driver["sendInvite"] is True
    assert driver["trackingMethod"] == TRACKING_METHOD_TURVO_APP
    assert driver["driverType"] == DRIVER_TYPE_SINGLE


@pytest.mark.asyncio
async def test_assign_driver_no_invite_uses_none_tracking_without_driver_type() -> None:
    client = AsyncMock()
    client.request = AsyncMock(return_value={"Status": "SUCCESS"})
    await assign_driver_to_shipment(
        "t3ra",
        "1000324895",
        carrier_order_id=653902,
        contact_id=640637,
        segment_id="seg-1",
        send_invite=False,
        client=client,
    )
    driver = client.request.await_args.kwargs["json_body"]["carrierOrder"][0]["drivers"][0]
    assert driver["sendInvite"] is False
    assert driver["trackingMethod"] == TRACKING_METHOD_NONE
    assert "driverType" not in driver
