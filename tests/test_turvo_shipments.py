"""Unit tests for Turvo shipments + documents integration modules.

``get_shipment`` lives under ``shipments``; POD checks use ``documents.list`` / ``documents.check_pod_by_shipment_id``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.integrations.turvo import documents as documents_module
from app.integrations.turvo import shipments as shipments_module
from app.integrations.turvo.public_api_client import TurvoApiError


class _FakeApiClient:
    def __init__(self, response: Any | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.request = AsyncMock(side_effect=self._handle)

    async def _handle(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


@pytest.mark.asyncio
async def test_get_shipment_calls_correct_endpoint_and_user():
    fake = _FakeApiClient(response={"id": 1000304706, "status": {"code": {"key": "2116"}}})

    out = await shipments_module.get_shipment(
        app_user_id="deb-test",
        shipment_id=1000304706,
        client=fake,
    )

    assert out == {"id": 1000304706, "status": {"code": {"key": "2116"}}}
    fake.request.assert_awaited_once_with(
        app_user_id="deb-test",
        method="GET",
        path="/shipments/1000304706",
    )


@pytest.mark.asyncio
async def test_get_shipment_propagates_api_error():
    fake = _FakeApiClient(error=TurvoApiError("boom", status_code=500, body="x"))

    with pytest.raises(TurvoApiError) as ei:
        await shipments_module.get_shipment(
            app_user_id="deb-test",
            shipment_id="1000304706",
            client=fake,
        )

    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_get_shipment_requires_shipment_id():
    fake = _FakeApiClient(response={})
    with pytest.raises(ValueError):
        await shipments_module.get_shipment(
            app_user_id="deb-test",
            shipment_id=None,
            client=fake,
        )
    fake.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_shipment_requires_app_user_id():
    fake = _FakeApiClient(response={})
    with pytest.raises(ValueError):
        await shipments_module.get_shipment(
            app_user_id="",
            shipment_id="1000304706",
            client=fake,
        )
    fake.request.assert_not_awaited()


def _sample_documents_list_pod_response() -> dict[str, Any]:
    return {
        "Status": "SUCCESS",
        "details": {
            "documents": [
                {
                    "id": "69f3151d29279d6965fa6b88",
                    "documentType": {"key": "3010", "value": "Proof of delivery"},
                    "documentName": "Proof of delivery - #30271",
                },
                {
                    "id": "other",
                    "documentType": {"key": "1000", "value": "Bill of lading"},
                },
            ]
        },
    }


@pytest.mark.asyncio
async def test_check_pod_by_shipment_id_requests_documents_list():
    fake = _FakeApiClient(response=_sample_documents_list_pod_response())

    out = await documents_module.check_pod_by_shipment_id(
        app_user_id="deb-test",
        shipment_id="1000304706",
        client=fake,
    )

    assert out["success"] is True
    assert out["pod_exists"] is True
    assert out["all_documents_count"] == 2
    assert len(out["pod_documents"]) == 1
    call = fake.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/documents/list"
    params = call.get("params") or {}
    assert "filter" in params
    assert "context" in params
    assert '"type":"SHIPMENT"' in params["context"]
    assert "1000304706" in params["context"]


@pytest.mark.asyncio
async def test_check_pod_by_shipment_id_no_pod():
    fake = _FakeApiClient(
        response={
            "Status": "SUCCESS",
            "details": {
                "documents": [
                    {"documentType": {"key": "1000", "value": "Bill of lading"}},
                ]
            },
        }
    )

    out = await documents_module.check_pod_by_shipment_id(
        app_user_id="deb-test",
        shipment_id=1000304706,
        client=fake,
    )

    assert out["success"] is True
    assert out["pod_exists"] is False
    assert out["pod_documents"] == []
    assert out["all_documents_count"] == 1


@pytest.mark.asyncio
async def test_check_pod_by_shipment_id_non_success_status():
    fake = _FakeApiClient(response={"Status": "ERROR", "details": {}})

    out = await documents_module.check_pod_by_shipment_id(
        app_user_id="deb-test",
        shipment_id="1000304706",
        client=fake,
    )

    assert out["success"] is False
    assert out["pod_exists"] is False
    assert out["all_documents_count"] == 0
    assert "ERROR" in out["message"] or "status" in out["message"].lower()


@pytest.mark.asyncio
async def test_check_pod_by_shipment_id_requires_shipment_id():
    fake = _FakeApiClient(response={})
    with pytest.raises(ValueError):
        await documents_module.check_pod_by_shipment_id(
            app_user_id="deb-test",
            shipment_id=None,
            client=fake,
        )
    fake.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_reexport_check_pod_from_shipments_module():
    """``shipments`` re-exports ``check_pod_by_shipment_id`` for backward compatibility."""
    fake = _FakeApiClient(response=_sample_documents_list_pod_response())
    out = await shipments_module.check_pod_by_shipment_id(
        app_user_id="deb-test",
        shipment_id="1000304706",
        client=fake,
    )
    assert out["pod_exists"] is True
