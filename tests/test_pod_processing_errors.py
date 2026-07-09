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
from app.models.activity_type import ActivityType
from app.workflows.nodes.pod import (
    classify_attachments,
    load_ratecon_analysis,
    pod_analysis,
    pod_vs_ratecon_analysis,
    ratecon_analysis,
)
from app.workflows.nodes.error_handler import record_workflow_failure_node
from app.workflows.nodes.turvo import upload_to_turvo


TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
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

@patch("app.workflows.nodes.pod.PodAttachmentNormalizeService")
def test_classify_attachments_failure_sets_error(mock_svc_cls):
    mock_svc_cls.return_value.normalize_from_state_data.return_value = {
        "success": False,
        "rejected": ["bad.txt"],
    }
    state = _state(
        attachment_bytes_by_id={"att-1": b"not-a-doc"},
        pod_attachment_stage_dir="/tmp/freightx/pod_staging/pod_email_mock",
        pod_attachment_stage_files=[{"attachment_id": "att-1", "path": "/tmp/freightx/pod_staging/pod_email_mock/att-1.bin"}],
    )

    result = classify_attachments(state)

    _assert_error(result, BusinessError.POD_ATTACHMENT_UPLOAD_FAILED)
    assert "attachment_bytes_by_id" not in result["data"]
    assert "pod_attachment_stage_dir" not in result["data"]
    assert "pod_attachment_stage_files" not in result["data"]


@patch("app.workflows.nodes.pod.PodAttachmentNormalizeService")
@patch("app.workflows.nodes.pod.insert_document")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_classify_attachments_success_does_not_set_error(mock_row, mock_insert, mock_svc_cls):
    mock_svc_cls.return_value.normalize_from_state_data.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "merged.pdf",
        "pod_merged_local_path": "/tmp/freightx/pod_staging/pod_email_mock/pod_SHIP.pdf",
        "classification_results": [],
        "rejected": [],
    }
    mock_insert.return_value = {"stored": True, "id": "doc-1"}
    state = _state(
        attachment_bytes_by_id={"att-1": b"%PDF-1.4"},
        pod_attachment_stage_dir="/tmp/freightx/pod_staging/pod_email_mock",
        pod_attachment_stage_files=[{"attachment_id": "att-1", "path": "/tmp/freightx/pod_staging/pod_email_mock/att-1.bin"}],
    )

    classify_attachments(state)

    assert "error" not in state.data
    assert "attachment_bytes_by_id" not in state.data
    assert state.data["pod_attachment_stage_dir"] == "/tmp/freightx/pod_staging/pod_email_mock"
    assert state.data["pod_merged_local_path"] == (
        "/tmp/freightx/pod_staging/pod_email_mock/pod_SHIP.pdf"
    )
    assert "pod_attachment_stage_files" not in state.data


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_cleans_stage_after_run(mock_tool, tmp_path):
    mock_tool.return_value = {
        "success": True,
        "findings": {"pod_data": {"delivery_confirmed": True}},
        "confidence_score": 0.9,
    }
    stage_dir = tmp_path / "pod_email_mock"
    stage_dir.mkdir()
    merged = stage_dir / "pod_SHIP.pdf"
    merged.write_bytes(b"%PDF-1.4 merged")
    state = _state(
        shipment_id="SHIP",
        pod_attachment_stage_dir=str(stage_dir),
        pod_merged_local_path=str(merged),
    )

    with patch(
        "app.workflows.nodes.pod.resolve_shipments_row_id_for_db",
        return_value=None,
    ):
        pod_analysis(state)

    assert "pod_attachment_stage_dir" not in state.data
    assert "pod_merged_local_path" not in state.data
    assert not stage_dir.exists()


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
def test_pod_analysis_extraction_empty_manual_soft_fail(mock_tool):
    mock_tool.return_value = {"success": False, "error": "extraction_empty"}
    state = _state(event_type="manual_pod_upload")

    pod_analysis(state)

    assert "error" not in state.data
    assert state.data["pod_analysis_results"]["error"] == "extraction_empty"


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
def test_pod_analysis_missing_shipment_id_sets_unexpected_failure(mock_tool):
    mock_tool.return_value = {"success": False, "error": "missing_shipment_id"}
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, SystemError.UNEXPECTED_NODE_FAILURE)


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_skipped_manual_soft_fail(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "no_pod_object_key",
    }
    state = _state(event_type="manual_pod_upload")

    pod_analysis(state)

    assert "error" not in state.data


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_skipped_sets_pod_extraction_empty(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "no_pod_object_key",
    }
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, BusinessError.POD_EXTRACTION_EMPTY)


@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_success_without_pod_data_sets_pod_extraction_empty(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "findings": {"pages": []},
        "confidence_score": 0.9,
        "document_id": "doc-1",
    }
    state = _state()

    result = pod_analysis(state)

    _assert_error(result, BusinessError.POD_EXTRACTION_EMPTY)


@patch("app.workflows.nodes.pod.get_pod_analysis")
@patch("app.workflows.nodes.pod.upsert_document_analysis")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_pod_analysis_success_does_not_set_error(mock_row, mock_upsert, mock_tool):
    mock_tool.return_value = {
        "success": True,
        "findings": {"pod_data": {"delivery_confirmed": True}, "pages": []},
        "confidence_score": 0.9,
        "document_id": "doc-1",
    }
    mock_upsert.return_value = {"stored": True, "id": "da-1"}
    state = _state()

    pod_analysis(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# ratecon_analysis
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_ratecon_analysis")
def test_ratecon_analysis_extraction_empty_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "extraction_empty"}
    state = _state()

    result = ratecon_analysis(state)

    _assert_error(result, BusinessError.RATECON_EXTRACTION_EMPTY)


@patch("app.workflows.nodes.pod.get_ratecon_analysis")
def test_ratecon_analysis_s3_failure_sets_error(mock_tool):
    mock_tool.return_value = {"success": False, "error": "s3_download_failed"}
    state = _state()

    result = ratecon_analysis(state)

    _assert_error(result, IntegrationError.POD_S3_DOWNLOAD_FAILED)


@patch("app.workflows.nodes.pod.get_ratecon_analysis")
def test_ratecon_analysis_skip_does_not_set_error(mock_tool):
    mock_tool.return_value = {
        "success": True,
        "skipped": True,
        "reason": "no_ratecon_document_in_db",
    }
    state = _state()

    ratecon_analysis(state)

    assert "error" not in state.data


# ---------------------------------------------------------------------------
# pod_vs_ratecon_analysis
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_comparison_manual_soft_fail(mock_tool):
    mock_tool.return_value = {"success": False, "error": "cross validation failed"}
    state = _state(event_type="manual_pod_upload")

    pod_vs_ratecon_analysis(state)

    assert "error" not in state.data


@patch("app.workflows.nodes.pod.get_pod_vs_ratecon_analysis")
def test_pod_vs_ratecon_comparison_exception_sets_unexpected(mock_tool):
    mock_tool.return_value = {"success": False, "error": "cross validation failed"}
    state = _state()

    result = pod_vs_ratecon_analysis(state)

    _assert_error(result, SystemError.UNEXPECTED_NODE_FAILURE)


# ---------------------------------------------------------------------------
# upload_to_turvo
# ---------------------------------------------------------------------------

@patch("app.workflows.nodes.turvo.PodTmsUploadService")
def test_upload_to_turvo_failure_sets_error(mock_svc_cls):
    mock_svc_cls.return_value.upload_merged_pod_from_state.return_value = {
        "success": False,
        "message": "TMS upload failed after retries",
    }
    state = _state()

    result = upload_to_turvo(state)

    _assert_error(result, IntegrationError.TMS_POD_UPLOAD_FAILED)


@patch("app.workflows.nodes.turvo.PodTmsUploadService")
def test_upload_to_turvo_success_does_not_set_error(mock_svc_cls):
    mock_svc_cls.return_value.upload_merged_pod_from_state.return_value = {
        "success": True,
        "document": {"id": "doc-turvo-1"},
    }
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


# ---------------------------------------------------------------------------
# POD failure → record_workflow_failure_node (node chain)
# ---------------------------------------------------------------------------


def _exception_metadata(mock_svc: MagicMock) -> dict:
    mock_svc.apply_sequence.assert_called_once()
    exception_cmd = mock_svc.apply_sequence.call_args[0][0]
    assert exception_cmd.activity_type == ActivityType.EXCEPTION
    return exception_cmd.metadata


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
@patch("app.workflows.nodes.pod.get_pod_analysis")
def test_pod_analysis_failure_flows_to_record_workflow_failure(
    mock_tool: MagicMock,
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    mock_tool.return_value = {"success": False, "error": "extraction_empty"}
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state(workflow_lifecycle_id=LIFECYCLE_ID)

    pod_analysis(state)

    assert state.data["error"]["code"] == BusinessError.POD_EXTRACTION_EMPTY.value
    assert state.data["error"]["message"] == BusinessError.POD_EXTRACTION_EMPTY.description

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)
    assert metadata["error"] == BusinessError.POD_EXTRACTION_EMPTY.value
    assert metadata["shipment_id"] == "SHP-001"
    assert metadata["load_id"] == "LD-001"
    assert metadata["error_description"] == BusinessError.POD_EXTRACTION_EMPTY.description
    mock_enqueue.assert_called_once()


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
@patch("app.workflows.nodes.pod.get_ratecon_analysis")
def test_ratecon_analysis_failure_flows_to_record_workflow_failure(
    mock_tool: MagicMock,
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    mock_tool.return_value = {"success": False, "error": "extraction_empty"}
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state(workflow_lifecycle_id=LIFECYCLE_ID)

    ratecon_analysis(state)

    assert state.data["error"]["code"] == BusinessError.RATECON_EXTRACTION_EMPTY.value

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)
    assert metadata["error"] == BusinessError.RATECON_EXTRACTION_EMPTY.value
    mock_enqueue.assert_called_once()
