"""API tests for POST /api/v1/appointment-scheduling/lifecycles/{id}/send."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_tenant_slug_for_user
from app.main import app
from app.services.appointment_scheduling.send_service import SendConflictError
from tests.helpers.auth_tokens import bearer_headers, make_test_api_user

_LIFECYCLE_UUID = "33333333-3333-3333-3333-333333333333"
_SEND_URL = f"/api/v1/appointment-scheduling/lifecycles/{_LIFECYCLE_UUID}/send"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _auth_and_overrides():
    user = make_test_api_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_tenant_slug_for_user] = lambda: "t3ra"
    yield
    app.dependency_overrides.clear()


def test_send_404_when_lifecycle_wrong_tenant(client) -> None:
    with patch(
        "app.api.v1.appointment_scheduling.SendService.validate_and_enqueue_draft_send",
        side_effect=ValueError("lifecycle_not_found"),
    ):
        resp = client.post(_SEND_URL, headers=bearer_headers(), json={})
    assert resp.status_code == 404
    assert resp.json()["message"] == "lifecycle_not_found"


def test_send_409_when_already_sent(client) -> None:
    with patch(
        "app.api.v1.appointment_scheduling.SendService.validate_and_enqueue_draft_send",
        side_effect=SendConflictError(
            "Draft email was already sent or lifecycle is not ready to send"
        ),
    ):
        resp = client.post(_SEND_URL, headers=bearer_headers(), json={})
    assert resp.status_code == 409
    message = resp.json()["message"].lower()
    assert "already sent" in message or "not ready" in message


def test_send_202_when_enqueued(client) -> None:
    with patch(
        "app.api.v1.appointment_scheduling.SendService.validate_and_enqueue_draft_send",
        return_value="exec-1",
    ) as mock_send:
        resp = client.post(
            _SEND_URL,
            headers=bearer_headers(),
            json={"shipment_id": "ship-row-1"},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["execution_id"] == "exec-1"
    assert body["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["tenant_slug"] == "t3ra"
    assert kwargs["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    assert kwargs["shipment_id"] == "ship-row-1"
