"""Auth behavior for /api/v1 routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_tenant_slug_for_user
from app.main import app
from tests.helpers.auth_tokens import bearer_headers, make_test_api_user

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_UPLOAD_POD_URL = f"/api/v1/shipments/{_SHIPMENTS_ROW_UUID}/upload_pod"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_upload_pod_401_without_bearer(client):
    resp = client.post(
        _UPLOAD_POD_URL,
        files={"file": ("pod.pdf", _MIN_PDF, "application/pdf")},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"


def test_upload_pod_403_when_header_tenant_conflicts(client, monkeypatch):
    user = make_test_api_user()
    app.dependency_overrides[get_current_user] = lambda: user

    monkeypatch.setattr(
        "app.core.request_context.TenantsDbRepository.get_slug_for_tenant_uuid",
        lambda self, tenant_uuid: "t3ra",
    )

    resp = client.post(
        _UPLOAD_POD_URL,
        headers={**bearer_headers(), "X-Tenant-Slug": "other-tenant"},
        files={"file": ("pod.pdf", _MIN_PDF, "application/pdf")},
    )
    assert resp.status_code == 403


def test_upload_pod_authenticated_success(client, monkeypatch):
    from app.services.pod_lifecycle.manual_upload_ingress_service import PodManualUploadEnqueueResult

    user = make_test_api_user()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_tenant_slug_for_user] = lambda: "t3ra"

    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_tms_partner_config",
        lambda self, slug: True,
    )
    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_oauth",
        lambda self, slug: True,
    )
    with patch(
        "app.api.v1.shipments.PodManualUploadIngressService.enqueue",
        return_value=PodManualUploadEnqueueResult(
            execution_id="exec-1",
            workflow_lifecycle_id="wl-1",
            shipment_id=_SHIPMENTS_ROW_UUID,
            object_key="pod_attachments/x.pdf",
            document_id="doc-1",
            celery_task_id="task-1",
            source="upload",
        ),
    ):
        resp = client.post(
            _UPLOAD_POD_URL,
            headers=bearer_headers(),
            files={"file": ("pod.pdf", _MIN_PDF, "application/pdf")},
        )
    assert resp.status_code == 202
    assert resp.json()["execution_id"] == "exec-1"
