"""
Tests for WorkflowException / @safe_node error handling in POD processing nodes.

Pattern mirrors test_calculate_tender_params.py:
  - mock the underlying tool so it returns a failure result
  - call the node function directly
  - assert state.data["error"]["code"] matches the expected catalog code
  - assert skip paths (skipped=True) do NOT set an error
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.error_catalog import BusinessError, IntegrationError, SystemError
from app.domain.state import WorkflowState
from app.workflows.nodes.pod import (
    classify_attachments,
    load_ratecon_analysis,
    pod_analysis,
    pod_vs_ratecon_analysis,
)
from app.workflows.nodes.turvo import upload_to_turvo


TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id="test-run-pod-errors",
        data={"shipment_id": "SHP-001", "load_id": "LD-001", **data},
    )


def _assert_error(result, expected_code):
    assert isinstance(result, dict), "safe_node should return dict on error"
    error = result["data"]["error"]
    assert error["code"] == expected_code.value if hasattr(expected_code, "value") else expected_code
    assert error["category"]
    assert error["message"]


# ---------------------------------------------------------------------------
# classify_attachments
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_normalized_attachments")
def test_classify_attachments_failure_sets_error(mock_normalize):
    def _set_failure(state):
        state.data["attachment_normalization"] = {"success": False, "rejected": ["bad.txt"]}
        state.data["pod_object_keys"] = []
        state.data["has_attachments"] = False

    mock_normalize.side_effect = _set_failure
    state = _state(pod_object_keys=["bad.txt"])

    result = classify_attachments(state)

    _assert_error(result, BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)


@patch("app.workflows.nodes.pod.get_normalized_attachments")
@patch("app.workflows.nodes.pod.insert_document")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_classify_attachments_success_does_not_set_error(mock_row, mock_insert, mock_normalize):
    def _set_success(state):
        state.data["attachment_normalization"] = {"success": True}
        state.data["pod_merged_pdf_object_key"] = "merged.pdf"
        state.data["pod_object_keys"] = ["merged.pdf"]
        state.data["has_attachments"] = True

    mock_normalize.side_effect = _set_success
    mock_insert.return_value = {"stored": True, "id": "doc-1"}
    state = _state(pod_object_keys=["a.pdf"])

    result = classify_attachments(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# load_ratecon_analysis
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.load_ratecon_analysis_tool")
def test_load_ratecon_analysis_missing_shipment_id_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "missing_shipment_id"}
    state = _state()
    state.data.pop("shipment_id", None)

    result = load_ratecon_analysis(state)

    _assert_error(result, SystemError.MISSING_SHIPMENT_ID)


@patch("app.workflows.nodes.pod.load_ratecon_analysis_tool")
def test_load_ratecon_analysis_s3_error_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "s3_download_failed"}
    state = _state()

    result = load_ratecon_analysis(state)

    _assert_error(result, IntegrationError.POD_S3_DOWNLOAD_FAILED)


@patch("app.workflows.nodes.pod.load_ratecon_analysis_tool")
def test_load_ratecon_analysis_skip_no_ratecon_does_not_set_error(mock_tool):
    """Intentional skip (ratecon not yet processed) must not raise."""
    mock_tool.return_value = {
        "success": False,
        "skipped": True,
        "reason": "no_ratecon_extraction",
    }
    state = _state()

    load_ratecon_analysis(state)

    assert "error" not in state.data


@patch("app.workflows.nodes.pod.load_ratecon_analysis_tool")
def test_load_ratecon_analysis_success_does_not_set_error(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "document_analysis_id": "da-1",
        "shipment_id": "SHP-001",
    }
    state = _state()

    load_ratecon_analysis(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# pod_analysis
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_extraction_empty_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "extraction_empty"}
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, BusinessError.POD_EXTRACTION_EMPTY)


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_s3_download_failed_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "s3_download_failed"}
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, IntegrationError.POD_S3_DOWNLOAD_FAILED)


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_missing_shipment_id_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "missing_shipment_id"}
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, SystemError.MISSING_SHIPMENT_ID)


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_skip_does_not_set_error(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "no_pod_object_key",
    }
    state = _state()

    pod_analysis(state)

    assert "error" not in state.data


@patch("app.workflows.nodes.pod.get_pod_analysis")
@patch("app.workflows.nodes.pod.upsert_document_analysis")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_pod_analysis_success_does_not_set_error(mock_row, mock_upsert, mock_tool):
    mock_tool.return_value = {
        "success": True,
        "findings": {"pages": []},
        "confidence_score": 0.9,
        "document_id": "doc-1",
    }
    mock_upsert.return_value = {"stored": True, "id": "da-1"}
    state = _state()

    pod_analysis(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# pod_vs_ratecon_analysis
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_missing_pod_data_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "missing_pod_data"}
    state = _state()

    result = pod_vs_ratecon_analysis(state)

    _assert_error(result, BusinessError.MISSING_POD_DATA)


@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_missing_ratecon_data_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "missing_ratecon_data"}
    state = _state()

    result = pod_vs_ratecon_analysis(state)

    _assert_error(result, BusinessError.MISSING_RATECON_DATA)


@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_skip_pod_analysis_not_success_does_not_set_error(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "pod_analysis_not_success",
    }
    state = _state()

    pod_vs_ratecon_analysis(state)

    assert "error" not in state.data


@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_skip_no_ratecon_analysis_does_not_set_error(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "no_ratecon_analysis",
    }
    state = _state()

    pod_vs_ratecon_analysis(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# upload_to_turvo
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.turvo.upload_to_turvo_tool")
def test_upload_to_turvo_failure_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "message": "TMS upload failed after retries"}
    state = _state()

    result = upload_to_turvo(state)

    _assert_error(result, IntegrationError.TMS_POD_UPLOAD_FAILED)


@patch("app.workflows.nodes.turvo.upload_to_turvo_tool")
def test_upload_to_turvo_success_does_not_set_error(mock_tool):
    mock_tool.return_value = {"success": True, "document": {"id": "doc-turvo-1"}}
    state = _state()

    upload_to_turvo(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# UNEXPECTED_NODE_FAILURE fallback via @safe_node
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_unexpected_exception_sets_unexpected_node_failure(mock_tool):
    mock_tool.side_effect = RuntimeError("unexpected db error")
    state = _state()

    result = pod_analysis(state)

    assert isinstance(result, dict)
    assert result["data"]["error"]["code"] == SystemError.UNEXPECTED_NODE_FAILURE.value
