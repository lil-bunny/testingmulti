"""Tests for POD vs ratecon validation activity log graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _base_state(*, data: dict | None = None) -> WorkflowState:
    payload = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "shipment_id": "1000324895",
        "shipments_row_id": "ship-row-1",
        "documents_pod": {"stored": True, "id": "doc-merged-1"},
        "pod_merged_pdf_object_key": "pod_attachments/pod_1000324895.pdf",
        "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
    }
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data=payload,
    )


@patch("app.workflows.nodes.record_pod_activity.PodPipelineActivityService")
def test_record_pod_vs_ratecon_activity_delegates_to_service(
    mock_service_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_vs_ratecon_activity

    mock_service = MagicMock()
    mock_service_cls.return_value = mock_service
    state = _base_state()

    record_pod_vs_ratecon_activity(state)

    mock_service.record_vs_ratecon_from_state.assert_called_once_with(state)


@patch("app.services.pod_pipeline_activity_service.WorkflowLifecycleService")
@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_validation_stored(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "document_uploaded",
    }

    state = _base_state(
        data={
            "document_analysis_pod_vs_ratecon": {
                "stored": True,
                "id": "analysis-vs-1",
            },
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "confidence_score": 0.91,
                "overall_status": "PASS",
                "validation_summary": "All fields match.",
            },
        }
    )

    PodPipelineActivityService(
        activity_log_service=mock_svc,
        lifecycle_service=mock_lc_cls.return_value,
    ).record_vs_ratecon_from_state(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert (
        sequence.steps[0].description
        == "POD validated against ratecon confidence=0.91 (PASS)"
    )
    assert sequence.steps[0].metadata == {"document_analysis_id": "analysis-vs-1"}


@patch("app.services.pod_pipeline_activity_service.WorkflowLifecycleService")
@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_validation_skipped(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "document_uploaded",
    }

    state = _base_state(
        data={
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "skipped": True,
                "reason": "comparison_skipped",
            },
        }
    )

    PodPipelineActivityService(
        activity_log_service=mock_svc,
        lifecycle_service=mock_lc_cls.return_value,
    ).record_vs_ratecon_from_state(state)

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert (
        sequence.steps[0].description
        == "POD vs ratecon validation skipped (comparison_skipped)"
    )
    assert sequence.steps[0].metadata == {"validation_skip_reason": "comparison_skipped"}


@patch("app.services.pod_pipeline_activity_service.WorkflowLifecycleService")
@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_validation_failed(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "document_uploaded",
    }

    state = _base_state(
        data={
            "pod_vs_ratecon_analysis_results": {
                "success": False,
                "error": "cross validation failed",
            },
        }
    )

    PodPipelineActivityService(
        activity_log_service=mock_svc,
        lifecycle_service=mock_lc_cls.return_value,
    ).record_vs_ratecon_from_state(state)

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == "POD vs ratecon validation failed"
    assert sequence.steps[0].metadata == {"error": "cross validation failed"}


@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_skips_without_extraction(
    mock_svc_cls: MagicMock,
) -> None:
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    state = _base_state()
    state.data.pop("document_analysis_pod")

    PodPipelineActivityService(activity_log_service=mock_svc_cls.return_value).record_vs_ratecon_from_state(
        state
    )
    mock_svc_cls.assert_not_called()


@patch("app.services.pod_pipeline_activity_service.WorkflowLifecycleService")
@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_idempotent_skip_email(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "document_processed",
    }

    state = _base_state(
        data={
            "event_type": "email_received",
            "document_analysis_pod_vs_ratecon": {
                "stored": True,
                "id": "analysis-vs-1",
            },
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "confidence_score": 0.91,
                "overall_status": "PASS",
            },
        }
    )

    PodPipelineActivityService(
        activity_log_service=mock_svc_cls.return_value,
        lifecycle_service=mock_lc_cls.return_value,
    ).record_vs_ratecon_from_state(state)
    mock_svc_cls.assert_not_called()


@patch("app.services.pod_pipeline_activity_service.WorkflowLifecycleService")
@patch("app.services.pod_pipeline_activity_service.ActivityLogService")
def test_record_pod_vs_ratecon_activity_manual_reupload_logs_when_already_processed(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.services.pod_pipeline_activity_service import PodPipelineActivityService

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "document_processed",
    }

    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "manual_pod_upload_source": "upload",
            "document_analysis_pod_vs_ratecon": {
                "stored": True,
                "id": "analysis-vs-1",
            },
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "confidence_score": 0.91,
                "overall_status": "PASS",
            },
        }
    )

    PodPipelineActivityService(
        activity_log_service=mock_svc,
        lifecycle_service=mock_lc_cls.return_value,
    ).record_vs_ratecon_from_state(state)
    mock_svc.record_sequence.assert_called_once()
