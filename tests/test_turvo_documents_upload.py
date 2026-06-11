"""Turvo document upload integration helpers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.domain.tenant_settings.tms import TmsSettings
from app.integrations.turvo import documents as documents_module
from app.integrations.turvo.public_api_client import TurvoApiClient


def _fake_tms() -> TmsSettings:
    return TmsSettings(
        public_api_url="https://my-sandbox-publicapi.turvo.com",
        client_id="publicapi",
        client_secret="secret",
        x_api_key="test-x-key",
        pod_document_lookup_id="20271627",
    )


@pytest.mark.asyncio
async def test_upload_pod_document_builds_multipart_params(monkeypatch):
    monkeypatch.setattr(TurvoApiClient, "_load_tms", lambda self, slug: _fake_tms())

    captured: dict = {}

    async def fake_multipart(self, tenant_slug, method, path, *, params=None, files=None, timeout_s=60.0):
        captured["tenant_slug"] = tenant_slug
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        captured["files"] = files
        return {
            "Status": "SUCCESS",
            "details": {
                "documentId": "doc-1",
                "documentName": "Proof of delivery - #1",
                "documentType": {"value": "Proof of delivery"},
            },
        }

    monkeypatch.setattr(TurvoApiClient, "request_multipart", fake_multipart)
    monkeypatch.setattr(
        TurvoApiClient,
        "_resolve_token",
        AsyncMock(return_value="tok"),
    )

    out = await documents_module.upload_pod_document(
        "t3ra",
        "1000324895",
        pdf_bytes=b"%PDF-1.4 test",
        filename="pod.pdf",
        document_name="Proof of delivery - #30389",
        lookup_id="20271627",
    )

    assert out["success"] is True
    assert out["document"]["id"] == "doc-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/documents"
    assert captured["files"]["attachment0"][0] == "pod.pdf"
    attrs = json.loads(captured["params"]["attributes"])
    assert attrs["lookupId"] == "20271627"


def test_parse_upload_response_error():
    out = documents_module.parse_upload_response({"Status": "ERROR"})
    assert out["success"] is False
