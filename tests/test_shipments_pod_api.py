"""API tests for POST /api/v1/shipments/{id}/upload_pod."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_tenant_slug_for_user
from app.main import app
from app.services.pod_manual_upload_ingress_service import (
    PodLifecycleNotFoundError,
    PodManualUploadEnqueueResult,
)
from app.services.pod_tms_upload_service import PodDocumentNotFoundError
from tests.helpers.auth_tokens import bearer_headers, make_test_api_user

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_UPLOAD_POD_URL = f"/api/v1/shipments/{_SHIPMENTS_ROW_UUID}/upload_pod"


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


def test_upload_pod_rejects_non_pdf(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_tms_partner_config",
        lambda self, slug: True,
    )
    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_oauth",
        lambda self, slug: True,
    )
    resp = client.post(
        _UPLOAD_POD_URL,
        headers=bearer_headers(),
        files={"file": ("bad.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 422


def test_upload_pod_401_when_not_linked(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_tms_partner_config",
        lambda self, slug: True,
    )
    monkeypatch.setattr(
        "app.api.deps.TurvoOAuthService.has_oauth",
        lambda self, slug: False,
    )
    resp = client.post(
        _UPLOAD_POD_URL,
        headers=bearer_headers(),
        files={"file": ("pod.pdf", _MIN_PDF, "application/pdf")},
    )
    assert resp.status_code == 401


def test_upload_pod_404_when_shipment_not_found(client, monkeypatch):
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
        side_effect=PodLifecycleNotFoundError("shipment not found"),
    ):
        resp = client.post(
            _UPLOAD_POD_URL,
            headers=bearer_headers(),
            files={"file": ("pod.pdf", _MIN_PDF, "application/pdf")},
        )
    assert resp.status_code == 404


def test_upload_pod_accepted_queues_workflow(client, monkeypatch):
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
    body = resp.json()
    assert body["execution_id"] == "exec-1"
    assert body["workflow_lifecycle_id"] == "wl-1"
    assert body["shipment_id"] == _SHIPMENTS_ROW_UUID
    assert body["message"] == "workflow queued"
    assert body["source"] == "upload"


def test_upload_pod_stored_document_accepted_without_file(client, monkeypatch):
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
            execution_id="exec-2",
            workflow_lifecycle_id="wl-2",
            shipment_id=_SHIPMENTS_ROW_UUID,
            object_key="pod_attachments/existing.pdf",
            document_id="doc-stored-1",
            celery_task_id="task-2",
            source="stored",
        ),
    ) as enqueue:
        resp = client.post(_UPLOAD_POD_URL, headers=bearer_headers())

    assert resp.status_code == 202
    body = resp.json()
    assert body["execution_id"] == "exec-2"
    assert body["object_key"] == "pod_attachments/existing.pdf"
    assert body["document_id"] == "doc-stored-1"
    assert body["source"] == "stored"
    enqueue.assert_called_once()
    assert enqueue.call_args.kwargs["pdf_bytes"] is None


def test_upload_pod_422_when_no_file_and_no_stored_document(client, monkeypatch):
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
        side_effect=PodDocumentNotFoundError("No POD document on file for shipment"),
    ):
        resp = client.post(_UPLOAD_POD_URL, headers=bearer_headers())

    assert resp.status_code == 422
    assert "No POD document on file" in resp.json()["message"]
