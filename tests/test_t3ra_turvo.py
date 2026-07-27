"""t3ra Turvo integration: API client, workflow tools, webhook mapping, and route handler."""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.domain.tenant_settings.tms import TmsSettings
from app.integrations.turvo import documents as documents_module
from app.integrations.turvo.load_to_shipment import (
    load_id_to_shipment_id_async,
    shipment_id_from_list_response,
)
from app.integrations.turvo.public_api_client import TurvoApiClient
from app.integrations.turvo.webhook_mapping import (
    TENDER_ACCEPTED_STATUS_CODE_KEY,
    map_turvo_status_webhook_to_payload,
)
from app.main import app
from app.tools import turvo as turvo_tool
from app.services.pod_lifecycle.ingress_service import (
    ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
    ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
    RouteCompletedDuplicateResult,
    RouteCompletedIngressGateResult,
)
from tests.e2e.fixtures.main import ROUTE_COMPLETE_WEBHOOK_PAYLOAD

_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_TURVO_SHIPMENT = "1000324868"


def _wire_ingress_route_gates(
    ingress_mock: MagicMock,
    *,
    convoy_skip: bool = False,
    pod_skip: bool = False,
) -> None:
    ingress_mock.check_route_completed_convoy_gate = AsyncMock(
        return_value=RouteCompletedIngressGateResult(
            skip=convoy_skip,
            reason=ROUTE_COMPLETED_SKIP_CONVOY_LOAD if convoy_skip else None,
        )
    )
    ingress_mock.check_route_completed_pod_gate = AsyncMock(
        return_value=RouteCompletedIngressGateResult(
            skip=pod_skip,
            reason=ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS if pod_skip else None,
        )
    )


class _FakeOAuthService:
    def __init__(self, tokens_sequence: list[Optional[dict[str, Any]]]):
        self._sequence = list(tokens_sequence)
        self.refresh_calls: list[str] = []

    async def get_tenant_tokens(self, tenant_slug: str, proactive_refresh: bool = True):
        if not self._sequence:
            return None
        return self._sequence.pop(0)

    async def refresh_tenant_token(self, tenant_slug: str):
        self.refresh_calls.append(tenant_slug)
        return {"success": True}


def _fake_tms() -> TmsSettings:
    return TmsSettings(
        public_api_url="https://my-sandbox-publicapi.turvo.com",
        x_api_key="test-x-key",
    )


def _httpx_response(status_code: int, body: dict | str | None = None) -> httpx.Response:
    if isinstance(body, dict):
        content = json.dumps(body).encode("utf-8")
        headers = {"content-type": "application/json"}
    elif isinstance(body, str):
        content = body.encode("utf-8")
        headers = {"content-type": "text/plain"}
    else:
        content = b""
        headers = {}
    return httpx.Response(status_code=status_code, content=content, headers=headers)


@pytest.mark.asyncio
async def test_turvo_api_client_request_and_401_refresh(monkeypatch: pytest.MonkeyPatch):
    """GET succeeds with token; 401 triggers refresh and retry."""
    monkeypatch.setattr(TurvoApiClient, "_load_tms", lambda self, slug: _fake_tms())
    captured: dict[str, Any] = {}
    responses = [
        _httpx_response(401, "unauthorized"),
        _httpx_response(200, {"id": 1}),
    ]
    seen_auth: list[str] = []

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        if len(seen_auth) == 0:
            captured["method"] = method
            captured["url"] = url
        seen_auth.append(headers["Authorization"])
        return responses.pop(0) if len(responses) > 1 else _httpx_response(200, {"id": 1})

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    oauth = _FakeOAuthService(
        [{"access_token": "tok-1"}, {"access_token": "tok-2"}]
    )
    client = TurvoApiClient(oauth_service=oauth)

    out = await client.request("t3ra", "GET", "/shipments/1")

    assert out == {"id": 1}
    assert oauth.refresh_calls == ["t3ra"]
    assert seen_auth == ["Bearer tok-1", "Bearer tok-2"]
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/v1/shipments/1")


def test_turvo_load_id_to_shipment_id_success():
    async def fake_async(tenant_slug: str, load_id: str) -> str:
        assert tenant_slug == "t3ra"
        assert load_id == "30381"
        return "1000315335"

    with (
        patch.object(turvo_tool, "_is_turvo_configured", return_value=True),
        patch.object(
            turvo_tool, "load_id_to_shipment_id_async", side_effect=fake_async
        ),
    ):
        out = turvo_tool.load_id_to_shipment_id(load_id="30381", tenant_slug="t3ra")

    assert out["success"] is True
    assert out["shipment_id"] == "1000315335"

    body = {
        "details": {
            "shipments": [{"id": 1000315335, "customId": "30381"}],
        },
    }
    assert shipment_id_from_list_response(body, "30381") == "1000315335"


@pytest.mark.asyncio
async def test_load_id_to_shipment_id_async_uses_custom_id_eq_first():
    class _FakeApi:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def request(self, tenant_slug: str, method: str, path: str, **kwargs: Any):
            self.calls.append({"tenant_slug": tenant_slug, "method": method, "path": path, **kwargs})
            return {
                "details": {
                    "shipments": [{"id": 1000315335, "customId": "30381"}],
                },
            }

    fake = _FakeApi()
    sid = await load_id_to_shipment_id_async("t3ra", "30381", client=fake)

    assert sid == "1000315335"
    assert len(fake.calls) == 1
    assert fake.calls[0]["params"] == {"customId[eq]": "30381"}


@pytest.mark.asyncio
async def test_load_id_to_shipment_id_async_falls_back_to_unfiltered_list():
    class _FakeApi:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def request(self, tenant_slug: str, method: str, path: str, **kwargs: Any):
            self.calls.append({"tenant_slug": tenant_slug, "method": method, "path": path, **kwargs})
            params = kwargs.get("params") or {}
            if "customId[eq]" in params:
                return {"details": {"shipments": []}}
            return {
                "details": {
                    "shipments": [
                        {"id": 1, "customId": "other"},
                        {"id": 1000315335, "customId": "30381"},
                    ],
                },
            }

    fake = _FakeApi()
    sid = await load_id_to_shipment_id_async("t3ra", "30381", client=fake)

    assert sid == "1000315335"
    assert len(fake.calls) == 2
    assert fake.calls[0]["params"] == {"customId[eq]": "30381"}
    assert "params" not in fake.calls[1]


@pytest.mark.asyncio
async def test_turvo_check_pod_by_shipment_id():
    """Documents list with POD type key is detected (pod_lifecycle gate)."""

    class _FakeApiClient:
        def __init__(self, response: Any):
            self._response = response
            self.calls: list[tuple[Any, ...]] = []
            self.request = AsyncMock(side_effect=self._handle)

        async def _handle(self, *args: Any, **kwargs: Any) -> Any:
            self.calls.append(args)
            return self._response

    response = {
        "Status": "SUCCESS",
        "details": {
            "documents": [
                {
                    "documentType": {"key": "3010", "value": "Proof of delivery"},
                },
                {
                    "documentType": {"key": "1000", "value": "Bill of lading"},
                },
            ]
        },
    }
    fake = _FakeApiClient(response)

    out = await documents_module.check_pod_by_shipment_id(
        tenant_slug="t3ra",
        shipment_id="1000304706",
        client=fake,
    )

    assert out["success"] is True
    assert out["pod_exists"] is True
    assert fake.calls[0][2] == "/documents/list"


def test_turvo_status_webhook_mapping_route_complete_only():
    route_body = {
        "tenantId": "1203",
        "eventName": "SHIPMENT_STATUS_UPDATE",
        "eventTime": "2026-04-27T10:46:48.245Z",
        "eventPayload": {
            "id": 1000304706,
            "status": {"code": {"key": "2116", "value": "Route complete"}},
        },
    }
    payload = map_turvo_status_webhook_to_payload(route_body)
    assert payload is not None
    assert payload["event_type"] == "route_completed"
    assert payload["shipment_id"] == "1000304706"

    other_body = {
        "tenantId": "1203",
        "eventName": "SHIPMENT_STATUS_UPDATE",
        "eventTime": "2026-04-27T10:46:48.245Z",
        "eventPayload": {
            "id": 1000304706,
            "status": {"code": {"key": "9999", "value": "In Transit"}},
        },
    }
    assert map_turvo_status_webhook_to_payload(other_body) is None


def test_turvo_webhook_queues_pod_lifecycle_when_ratecon_lifecycle_found() -> None:
    lifecycle = {
        "found": True,
        "lifecycle_id": "11111111-2222-3333-4444-555555555555",
    }
    from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult

    with (
        patch("app.api.v1.webhooks.ShipmentsService") as shipments_cls,
        patch("app.api.v1.webhooks.WorkflowLifecycleService") as lifecycle_cls,
        patch("app.api.v1.webhooks.CommunicationsService") as comm_cls,
        patch("app.api.v1.webhooks.PodLifecycleIngressService") as ingress_cls,
        patch("app.api.v1.webhooks.IngressService") as scheduling_cls,
        patch("app.api.v1.webhooks.LifecycleRunSerializerService") as serializer_cls,
        patch(
            "app.api.v1.webhooks.resolve_graph_tenant_to_uuid",
            return_value="tenant-uuid-1",
        ),
    ):
        scheduling_cls.return_value.handle_shipment_update = AsyncMock(
            return_value=MagicMock(handled=False, enqueued=False, skip_reason=None)
        )
        shipments_cls.return_value.get_by_shipment_number.return_value = {
            "id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        }
        lifecycle_cls.return_value.read_lifecycle.return_value = lifecycle
        comm_cls.return_value.resolve_thread_for_lifecycle.return_value = "thread-from-comm"
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(is_duplicate=False)
        )
        _wire_ingress_route_gates(ingress_cls.return_value)
        serializer_cls.return_value.resolve_then_enqueue.return_value = (
            SerializeEnqueueResult(
                lifecycle_id="pod-lc-1",
                inbox_key="inbox:lifecycle:pod-lc-1",
                status="started",
                celery_task_id="celery-task-1",
                workflow_lifecycle_id="pod-lc-1",
            )
        )

        client = TestClient(app)
        resp = client.post("/api/v1/webhook/turvo", json=ROUTE_COMPLETE_WEBHOOK_PAYLOAD)

    assert resp.status_code == 200
    assert resp.json().get("execution_id")

    lifecycle_cls.return_value.read_lifecycle.assert_called_once()
    read_kw = lifecycle_cls.return_value.read_lifecycle.call_args.kwargs
    assert read_kw["workflow_name"] == "ratecon"
    assert read_kw["shipment_id"] == _SHIPMENTS_ROW_UUID

    comm_cls.return_value.resolve_thread_for_lifecycle.assert_called_once_with(
        tenant_id="tenant-uuid-1",
        workflow_lifecycle_id="11111111-2222-3333-4444-555555555555",
    )

    ser_kw = serializer_cls.return_value.resolve_then_enqueue.call_args.kwargs
    assert ser_kw["workflow_name"] == "pod_lifecycle"
    assert ser_kw["payload"]["shipment_id"] == _TURVO_SHIPMENT
    assert ser_kw["payload"]["event_type"] == "route_completed"
    assert ser_kw["payload"]["thread_id"] == "thread-from-comm"


def test_turvo_webhook_scheduling_handled_short_circuits_pod_path() -> None:
    """Appointment scheduling ingress handled=True must skip POD route_completed path."""
    with (
        patch("app.api.v1.webhooks.IngressService") as scheduling_cls,
        patch("app.api.v1.webhooks.PodLifecycleIngressService") as pod_cls,
        patch("app.api.v1.webhooks.ShipmentsService") as shipments_cls,
        patch("app.api.v1.webhooks.run_workflow_async") as celery_task,
    ):
        scheduling_cls.return_value.handle_shipment_update = AsyncMock(
            return_value=MagicMock(
                handled=True,
                enqueued=True,
                execution_id="sched-exec-1",
                skip_reason=None,
            )
        )

        client = TestClient(app)
        resp = client.post(
            "/api/v1/webhook/turvo",
            json={
                "eventName": "SHIPMENT_UPDATE",
                "eventPayload": {
                    "id": 1000324868,
                    "load": {"id": 47361},
                    "status": {
                        "code": {
                            "key": TENDER_ACCEPTED_STATUS_CODE_KEY,
                            "value": "Tender - accepted",
                        }
                    },
                },
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"execution_id": "sched-exec-1"}
    scheduling_cls.return_value.handle_shipment_update.assert_awaited_once()
    pod_cls.assert_not_called()
    shipments_cls.assert_not_called()
    celery_task.apply_async.assert_not_called()


def test_turvo_webhook_skips_duplicate_route_completed() -> None:
    lifecycle = {
        "found": True,
        "lifecycle_id": "11111111-2222-3333-4444-555555555555",
    }
    pod_lifecycle_id = "22222222-3333-4444-5555-666666666666"

    with (
        patch("app.api.v1.webhooks.ShipmentsService") as shipments_cls,
        patch("app.api.v1.webhooks.WorkflowLifecycleService") as lifecycle_cls,
        patch("app.api.v1.webhooks.CommunicationsService") as comm_cls,
        patch("app.api.v1.webhooks.PodLifecycleIngressService") as ingress_cls,
        patch("app.api.v1.webhooks.LifecycleRunSerializerService") as serializer_cls,
        patch(
            "app.api.v1.webhooks.resolve_graph_tenant_to_uuid",
            return_value="tenant-uuid-1",
        ),
    ):
        shipments_cls.return_value.get_by_shipment_number.return_value = {
            "id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        }
        lifecycle_cls.return_value.read_lifecycle.return_value = lifecycle
        comm_cls.return_value.resolve_thread_for_lifecycle.return_value = "thread-from-comm"
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(
                is_duplicate=True,
                lifecycle_id=pod_lifecycle_id,
            )
        )

        client = TestClient(app)
        resp = client.post("/api/v1/webhook/turvo", json=ROUTE_COMPLETE_WEBHOOK_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("skipped") == "duplicate_route_completed"
    assert body.get("lifecycle_id") == pod_lifecycle_id
    assert "execution_id" not in body
    serializer_cls.return_value.resolve_then_enqueue.assert_not_called()


def test_turvo_webhook_skips_convoy_load() -> None:
    lifecycle = {
        "found": True,
        "lifecycle_id": "11111111-2222-3333-4444-555555555555",
    }

    with (
        patch("app.api.v1.webhooks.ShipmentsService") as shipments_cls,
        patch("app.api.v1.webhooks.WorkflowLifecycleService") as lifecycle_cls,
        patch("app.api.v1.webhooks.CommunicationsService") as comm_cls,
        patch("app.api.v1.webhooks.PodLifecycleIngressService") as ingress_cls,
        patch("app.api.v1.webhooks.LifecycleRunSerializerService") as serializer_cls,
        patch(
            "app.api.v1.webhooks.resolve_graph_tenant_to_uuid",
            return_value="tenant-uuid-1",
        ),
    ):
        shipments_cls.return_value.get_by_shipment_number.return_value = {
            "id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        }
        lifecycle_cls.return_value.read_lifecycle.return_value = lifecycle
        comm_cls.return_value.resolve_thread_for_lifecycle.return_value = "thread-from-comm"
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(is_duplicate=False)
        )
        _wire_ingress_route_gates(ingress_cls.return_value, convoy_skip=True)

        client = TestClient(app)
        resp = client.post("/api/v1/webhook/turvo", json=ROUTE_COMPLETE_WEBHOOK_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("skipped") == ROUTE_COMPLETED_SKIP_CONVOY_LOAD
    assert body.get("shipment_id") == _TURVO_SHIPMENT
    assert "execution_id" not in body
    serializer_cls.return_value.resolve_then_enqueue.assert_not_called()


def test_turvo_webhook_skips_pod_already_exists() -> None:
    lifecycle = {
        "found": True,
        "lifecycle_id": "11111111-2222-3333-4444-555555555555",
    }

    with (
        patch("app.api.v1.webhooks.ShipmentsService") as shipments_cls,
        patch("app.api.v1.webhooks.WorkflowLifecycleService") as lifecycle_cls,
        patch("app.api.v1.webhooks.CommunicationsService") as comm_cls,
        patch("app.api.v1.webhooks.PodLifecycleIngressService") as ingress_cls,
        patch("app.api.v1.webhooks.LifecycleRunSerializerService") as serializer_cls,
        patch(
            "app.api.v1.webhooks.resolve_graph_tenant_to_uuid",
            return_value="tenant-uuid-1",
        ),
    ):
        shipments_cls.return_value.get_by_shipment_number.return_value = {
            "id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        }
        lifecycle_cls.return_value.read_lifecycle.return_value = lifecycle
        comm_cls.return_value.resolve_thread_for_lifecycle.return_value = "thread-from-comm"
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(is_duplicate=False)
        )
        _wire_ingress_route_gates(ingress_cls.return_value, pod_skip=True)

        client = TestClient(app)
        resp = client.post("/api/v1/webhook/turvo", json=ROUTE_COMPLETE_WEBHOOK_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body.get("skipped") == ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS
    assert body.get("shipment_id") == _TURVO_SHIPMENT
    assert "execution_id" not in body
    serializer_cls.return_value.resolve_then_enqueue.assert_not_called()

