"""Unit tests for POD activity metadata builders."""

from __future__ import annotations

import pytest

from app.domain.pod_lifecycle.activity_metadata import (
    POD_ACTIVITY_METADATA_FORBIDDEN_KEYS,
    assert_no_forbidden_keys,
    compact,
    extraction_action_metadata,
    processed_failure_action_metadata,
    reminder_action_metadata,
    tms_action_metadata,
    upload_action_metadata,
    upload_failure_action_metadata,
)


def test_compact_returns_none_for_empty() -> None:
    assert compact() is None
    assert compact(foo=None, bar="") is None


def test_compact_omits_empty_values() -> None:
    assert compact(a=1, b=None, c="") == {"a": 1}


def test_upload_action_metadata_email_basenames_only() -> None:
    meta = upload_action_metadata(
        {
            "event_type": "email_received",
            "pod_merged_pdf_object_key": "pod_attachments/pod_1000324895.pdf",
            "pod_source_object_keys": ["pod_attachments/pod_1000324895.pdf"],
        },
        documents_pod={"id": "doc-1", "stored": True},
    )
    assert meta == {
        "object_key": "pod_attachments/pod_1000324895.pdf",
        "document_id": "doc-1",
        "source_object_keys": ["pod_1000324895.pdf"],
    }
    assert_no_forbidden_keys(meta)


def test_upload_action_metadata_manual_no_source_keys() -> None:
    meta = upload_action_metadata(
        {
            "event_type": "manual_pod_upload",
            "pod_merged_pdf_object_key": "pod_attachments/manual.pdf",
        },
        documents_pod={"id": "doc-2"},
    )
    assert meta == {
        "object_key": "pod_attachments/manual.pdf",
        "document_id": "doc-2",
    }
    assert_no_forbidden_keys(meta)


def test_upload_failure_action_metadata() -> None:
    meta = upload_failure_action_metadata(
        {"attachment_normalization": {"success": False, "error": "PDF merge failed"}}
    )
    assert meta == {"error": "PDF merge failed"}
    assert_no_forbidden_keys(meta)


def test_processed_failure_action_metadata() -> None:
    meta = processed_failure_action_metadata(
        {"pod_analysis_results": {"success": False, "reason": "extraction_empty"}}
    )
    assert meta == {"error": "extraction_empty"}
    assert_no_forbidden_keys(meta)


def test_extraction_action_metadata_id_only() -> None:
    meta = extraction_action_metadata(
        {"stored": True, "id": "analysis-1"},
    )
    assert meta == {"document_analysis_id": "analysis-1"}
    assert_no_forbidden_keys(meta)


def test_reminder_action_metadata() -> None:
    meta = reminder_action_metadata(2)
    assert meta == {"reminder_step": 2}
    assert_no_forbidden_keys(meta)


def test_tms_action_metadata_allowlist_only() -> None:
    meta = tms_action_metadata(
        outcome="uploaded",
        extra={
            "tms_document_id": "tms-doc-1",
            "uploaded_by": "portal-user",
            "shipment_id": "should-not-appear",
            "optimization": {"optimized": False},
        },
    )
    assert meta == {
        "tms_document_id": "tms-doc-1",
        "uploaded_by": "portal-user",
        "outcome": "uploaded",
    }
    assert_no_forbidden_keys(meta)


@pytest.mark.parametrize("key", sorted(POD_ACTIVITY_METADATA_FORBIDDEN_KEYS))
def test_forbidden_keys_documented(key: str) -> None:
    assert isinstance(key, str) and key
