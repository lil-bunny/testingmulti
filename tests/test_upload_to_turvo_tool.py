"""Tests for app.tools.turvo.upload_to_turvo workflow tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.tools import turvo as turvo_tool

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"
_OBJECT_KEY = "pod_attachments/merged.pdf"


def _real_s3_download(key: str) -> dict:
    return {
        "success": True,
        "body": _MIN_PDF,
        "object_key": key,
        "error_message": None,
    }


def test_upload_to_turvo_success(monkeypatch):
    monkeypatch.setattr(turvo_tool, "_is_turvo_configured", lambda slug: True)
    monkeypatch.setattr(
        turvo_tool.bucket,
        "download_object_bytes",
        _real_s3_download,
    )

    with patch(
        "app.tools.turvo.resolve_pod_lookup_id",
        new=AsyncMock(return_value="lookup-1"),
    ), patch(
        "app.tools.turvo.get_shipment_async",
        new=AsyncMock(return_value={"details": {"customId": "30389"}}),
    ), patch(
        "app.tools.turvo.upload_pod_document",
        new=AsyncMock(
            return_value={
                "success": True,
                "message": "ok",
                "document": {"id": "tms-1", "name": "POD", "type": "proof_of_delivery"},
            }
        ),
    ):
        out = turvo_tool.upload_to_turvo(
            {
                "tenant_slug": "t3ra",
                "shipment_id": "1000324895",
                "pod_merged_pdf_object_key": _OBJECT_KEY,
            }
        )

    assert out["success"] is True
    assert out["document"]["id"] == "tms-1"


def test_upload_to_turvo_succeeds_with_body_only_not_content(monkeypatch):
    """Regression: S3 service returns ``body``, not ``content``."""
    monkeypatch.setattr(turvo_tool, "_is_turvo_configured", lambda slug: True)
    monkeypatch.setattr(
        turvo_tool.bucket,
        "download_object_bytes",
        lambda key: {
            "success": True,
            "body": _MIN_PDF,
            "object_key": key,
            "error_message": None,
        },
    )

    with patch(
        "app.tools.turvo.resolve_pod_lookup_id",
        new=AsyncMock(return_value="lookup-1"),
    ), patch(
        "app.tools.turvo.get_shipment_async",
        new=AsyncMock(return_value={"details": {}}),
    ), patch(
        "app.tools.turvo.upload_pod_document",
        new=AsyncMock(return_value={"success": True, "message": "ok", "document": {"id": "tms-2"}}),
    ) as upload_mock:
        out = turvo_tool.upload_to_turvo(
            {
                "tenant_slug": "t3ra",
                "shipment_id": "1000324895",
                "pod_object_keys": [_OBJECT_KEY],
            }
        )

    assert out["success"] is True
    upload_mock.assert_awaited_once()
    assert upload_mock.await_args.kwargs["pdf_bytes"] == _MIN_PDF


def test_upload_to_turvo_fails_when_only_content_not_body(monkeypatch):
    monkeypatch.setattr(turvo_tool, "_is_turvo_configured", lambda slug: True)
    monkeypatch.setattr(
        turvo_tool.bucket,
        "download_object_bytes",
        lambda key: {"success": True, "content": _MIN_PDF},
    )

    out = turvo_tool.upload_to_turvo(
        {
            "tenant_slug": "t3ra",
            "shipment_id": "1000324895",
            "pod_merged_pdf_object_key": _OBJECT_KEY,
        }
    )

    assert out["success"] is False
    assert out["message"] == "S3 download failed"


def test_upload_to_turvo_optimizes_oversized_pdf_before_upload(monkeypatch):
    large_pdf = b"%PDF-1.4\n" + b"x" * (11 * 1024 * 1024)
    small_pdf = b"%PDF-1.4\noptimized\n"

    monkeypatch.setattr(turvo_tool, "_is_turvo_configured", lambda slug: True)
    monkeypatch.setattr(
        turvo_tool.bucket,
        "download_object_bytes",
        lambda key: {"success": True, "body": large_pdf},
    )
    monkeypatch.setattr(
        turvo_tool,
        "optimize_for_tms_upload",
        lambda pdf_bytes, **kwargs: (small_pdf, {"optimized": True, "original_bytes": len(pdf_bytes)}),
    )

    with patch(
        "app.tools.turvo.resolve_pod_lookup_id",
        new=AsyncMock(return_value="lookup-1"),
    ), patch(
        "app.tools.turvo.get_shipment_async",
        new=AsyncMock(return_value={"details": {}}),
    ), patch(
        "app.tools.turvo.upload_pod_document",
        new=AsyncMock(return_value={"success": True, "message": "ok", "document": {"id": "tms-3"}}),
    ) as upload_mock:
        out = turvo_tool.upload_to_turvo(
            {
                "tenant_slug": "t3ra",
                "shipment_id": "1000324895",
                "pod_merged_pdf_object_key": _OBJECT_KEY,
            }
        )

    assert out["success"] is True
    assert out["optimization"]["optimized"] is True
    assert upload_mock.await_args.kwargs["pdf_bytes"] == small_pdf


def test_upload_to_turvo_missing_merged_key(monkeypatch):
    monkeypatch.setattr(
        turvo_tool,
        "resolve_merged_pod_object_key",
        lambda data: (None, {}),
    )
    out = turvo_tool.upload_to_turvo(
        {"tenant_slug": "t3ra", "shipment_id": "1000324895"}
    )
    assert out["success"] is False
    assert "missing_pod_merged_pdf_object_key" in out["message"]


def test_upload_to_turvo_pdf_too_large_returns_error_key(monkeypatch):
    large_pdf = b"%PDF-1.4\n" + b"x" * (11 * 1024 * 1024)
    monkeypatch.setattr(turvo_tool, "_is_turvo_configured", lambda slug: True)
    monkeypatch.setattr(
        turvo_tool.bucket,
        "download_object_bytes",
        lambda key: {"success": True, "body": large_pdf},
    )

    def _raise_too_large(pdf_bytes, **kwargs):
        raise turvo_tool.PdfTooLargeError("over budget")

    monkeypatch.setattr(turvo_tool, "optimize_for_tms_upload", _raise_too_large)

    out = turvo_tool.upload_to_turvo(
        {
            "tenant_slug": "t3ra",
            "shipment_id": "1000324895",
            "pod_merged_pdf_object_key": _OBJECT_KEY,
        }
    )
    assert out["success"] is False
    assert out["error"] == "pdf_too_large"
    assert out["message"] == "pdf_too_large"
