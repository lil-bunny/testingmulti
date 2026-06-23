"""API tests for POST /api/v1/workflow-lifecycles/{id}/acknowledge|resolve."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.services.workflow_review_service import (
    WorkflowLifecycleNotFoundError,
    WorkflowReviewAcknowledgeResult,
    WorkflowReviewResolveResult,
)
from tests.helpers.auth_tokens import bearer_headers, make_test_api_user

_LIFECYCLE_UUID = "22222222-2222-2222-2222-222222222222"
_ACK_URL = f"/api/v1/workflow-lifecycles/{_LIFECYCLE_UUID}/acknowledge"
_RESOLVE_URL = f"/api/v1/workflow-lifecycles/{_LIFECYCLE_UUID}/resolve"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _auth_and_overrides():
    user = make_test_api_user()
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def test_acknowledge_422_blank_comment(client) -> None:
    resp = client.post(_ACK_URL, headers=bearer_headers(), json={"comment": "   "})
    assert resp.status_code == 422


def test_acknowledge_422_invalid_lifecycle_uuid(client) -> None:
    resp = client.post(
        "/api/v1/workflow-lifecycles/$b6175ca1-da8d-4397-b935-212ed07a1ca3/acknowledge",
        headers=bearer_headers(),
        json={"comment": "Looks good"},
    )
    assert resp.status_code == 422
    assert "invalid workflow_lifecycle_id" in resp.json()["message"]


def test_resolve_422_invalid_lifecycle_uuid(client) -> None:
    resp = client.post(
        "/api/v1/workflow-lifecycles/not-a-uuid/resolve",
        headers=bearer_headers(),
        json={"comment": "Handled manually"},
    )
    assert resp.status_code == 422
    assert "invalid workflow_lifecycle_id" in resp.json()["message"]


def test_acknowledge_404_when_lifecycle_not_found(client) -> None:
    with patch(
        "app.api.v1.workflow_lifecycles.WorkflowReviewService.acknowledge",
        side_effect=WorkflowLifecycleNotFoundError("workflow lifecycle not found"),
    ):
        resp = client.post(
            _ACK_URL, headers=bearer_headers(), json={"comment": "Looks good"}
        )
    assert resp.status_code == 404


def test_acknowledge_200_success(client) -> None:
    with patch(
        "app.api.v1.workflow_lifecycles.WorkflowReviewService.acknowledge",
        return_value=WorkflowReviewAcknowledgeResult(
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            workflow_name="load_tendering",
            activity_log_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        ),
    ):
        resp = client.post(
            _ACK_URL, headers=bearer_headers(), json={"comment": "Looks good"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    assert body["workflow_name"] == "load_tendering"
    assert body["activity_log_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"


def test_resolve_422_blank_comment(client) -> None:
    resp = client.post(_RESOLVE_URL, headers=bearer_headers(), json={"comment": ""})
    assert resp.status_code == 422


def test_resolve_404_when_lifecycle_not_found(client) -> None:
    with patch(
        "app.api.v1.workflow_lifecycles.WorkflowReviewService.resolve",
        side_effect=WorkflowLifecycleNotFoundError("workflow lifecycle not found"),
    ):
        resp = client.post(
            _RESOLVE_URL, headers=bearer_headers(), json={"comment": "Handled manually"}
        )
    assert resp.status_code == 404


def test_resolve_200_marks_resolved_manually(client) -> None:
    with patch(
        "app.api.v1.workflow_lifecycles.WorkflowReviewService.resolve",
        return_value=WorkflowReviewResolveResult(
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            workflow_name="load_tendering",
            activity_log_ids=[
                "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "ffffffff-ffff-ffff-ffff-ffffffffffff",
            ],
            to_status="completed",
            to_sub_status="resolved_manually",
        ),
    ):
        resp = client.post(
            _RESOLVE_URL, headers=bearer_headers(), json={"comment": "Handled manually"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    assert body["to_status"] == "completed"
    assert body["to_sub_status"] == "resolved_manually"
    assert len(body["activity_log_ids"]) == 2
