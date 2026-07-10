"""Tests for Turvo shipment driver assignment payload."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.turvo.shipments import (
    DRIVER_TYPE_SINGLE,
    TRACKING_METHOD_NONE,
    TRACKING_METHOD_TURVO_APP,
    assign_driver_to_shipment,
    driver_assignment_row_ids_from_carrier_order,
    replace_driver_on_shipment,
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


def test_driver_assignment_row_ids_ignores_deleted_and_missing_id() -> None:
    order = {
        "deleted": False,
        "drivers": [
            {"deleted": False, "id": "row-a", "context": {"id": 640635}},
            {"deleted": True, "id": "row-b"},
            {"deleted": False, "context": {"id": 640637}},
            {"deleted": False, "id": "row-c", "driverId": 640638},
        ],
    }
    assert driver_assignment_row_ids_from_carrier_order(order) == ["row-a", "row-c"]


def test_driver_assignment_row_ids_uses_driver_assignment_id_fallback() -> None:
    order = {
        "deleted": False,
        "drivers": [
            {"deleted": False, "driverAssignmentId": 37477, "context": {"id": 640635}},
        ],
    }
    assert driver_assignment_row_ids_from_carrier_order(order) == ["37477"]


@pytest.mark.asyncio
async def test_replace_driver_builds_delete_and_add_operations() -> None:
    client = AsyncMock()
    client.request = AsyncMock(return_value={"Status": "SUCCESS"})
    await replace_driver_on_shipment(
        "t3ra",
        "1000324895",
        carrier_order_id=653902,
        contact_id=640637,
        assignment_row_ids=["100", "101"],
        segment_id="seg-1",
        send_invite=False,
        client=client,
    )
    drivers = client.request.await_args.kwargs["json_body"]["carrierOrder"][0]["drivers"]
    assert drivers[0] == {"driverAssignmentId": 100, "_operation": 2}
    assert drivers[1] == {"driverAssignmentId": 101, "_operation": 2}
    add = drivers[2]
    assert add["driverId"] == 640637
    assert add["_operation"] == 0
    assert add["trackingMethod"] == TRACKING_METHOD_NONE
