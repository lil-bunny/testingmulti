"""Tests for Turvo driver contact create (optional email)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.integrations.turvo.contacts import create_driver_contact


@pytest.mark.asyncio
async def test_create_driver_contact_omits_email_when_absent() -> None:
    client = AsyncMock()
    client.request = AsyncMock(return_value={"details": {"id": 640637}})
    contact_id = await create_driver_contact(
        "t3ra",
        name="Virat",
        phone="9989239823",
        email=None,
        carrier_id=848297,
        carrier_name="Test Carrier",
        client=client,
    )
    assert contact_id == 640637
    body = client.request.await_args.kwargs["json_body"]
    assert "email" not in body
    assert body["phone"][0]["number"] == "9989239823"
