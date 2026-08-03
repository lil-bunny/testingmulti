"""Tests for POD-vs-TMS batch rescore service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.pod_lifecycle.pod_score_result import PodScoreResult
from app.models.document_analysis import DocumentAnalysisType
from app.services.pod_lifecycle.pod_vs_tms_rescore_service import (
    MAX_BATCH_SIZE,
    PodVsTmsRescoreService,
)
from app.services.pod_lifecycle.tms_upload_service import PodDocumentNotFoundError


_SHIP_UUID = "11111111-1111-1111-1111-111111111111"
_TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _service(
    *,
    shipments: MagicMock | None = None,
    staging: MagicMock | None = None,
    tenants: MagicMock | None = None,
) -> PodVsTmsRescoreService:
    return PodVsTmsRescoreService(
        shipments_service=shipments or MagicMock(),
        staging_service=staging or MagicMock(),
        tenants_service=tenants or MagicMock(),
    )


@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.apply_async_on_work_queue")
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.resolve_graph_tenant_to_uuid",
    return_value=_TENANT_UUID,
)
def test_enqueue_batch_queues_one_task_per_shipment(mock_resolve, mock_apply) -> None:
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "id": _SHIP_UUID,
        "shipment_number": "62762",
    }
    staging = MagicMock()
    staging.resolve_stored_pod_document.return_value = SimpleNamespace(
        storage_key="pod_attachments/x.pdf",
        document_id="doc-1",
    )
    mock_apply.return_value = SimpleNamespace(id="celery-1")

    svc = _service(shipments=shipments, staging=staging)
    items = svc.enqueue_batch(
        tenant_slug="t3ra",
        shipment_ids=[_SHIP_UUID],
        use_existing_extraction=True,
    )

    assert len(items) == 1
    assert items[0].status == "queued"
    assert items[0].celery_task_id == "celery-1"
    assert items[0].shipment_number == "62762"
    mock_apply.assert_called_once()
    kwargs = mock_apply.call_args.kwargs
    assert kwargs["tenant_slug"] == "t3ra"
    assert kwargs["kwargs"]["shipment_id"] == _SHIP_UUID
    assert kwargs["kwargs"]["use_existing_extraction"] is True
    mock_resolve.assert_called_once_with("t3ra")


@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.resolve_graph_tenant_to_uuid",
    return_value=_TENANT_UUID,
)
def test_enqueue_batch_not_found(mock_resolve) -> None:
    shipments = MagicMock()
    shipments.get_by_id.return_value = None
    svc = _service(shipments=shipments)
    items = svc.enqueue_batch(
        tenant_slug="t3ra",
        shipment_ids=[_SHIP_UUID],
    )
    assert items[0].status == "not_found"
    mock_resolve.assert_called_once()


@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.resolve_graph_tenant_to_uuid",
    return_value=_TENANT_UUID,
)
def test_enqueue_batch_no_pod_document(mock_resolve) -> None:
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "id": _SHIP_UUID,
        "shipment_number": "62762",
    }
    staging = MagicMock()
    staging.resolve_stored_pod_document.side_effect = PodDocumentNotFoundError(
        "No POD document on file for shipment"
    )
    svc = _service(shipments=shipments, staging=staging)
    items = svc.enqueue_batch(
        tenant_slug="t3ra",
        shipment_ids=[_SHIP_UUID],
    )
    assert items[0].status == "no_pod_document"
    mock_resolve.assert_called_once()


def test_enqueue_batch_rejects_oversized() -> None:
    svc = _service()
    with pytest.raises(ValueError, match="max batch size"):
        svc.enqueue_batch(
            tenant_slug="t3ra",
            shipment_ids=[_SHIP_UUID] * (MAX_BATCH_SIZE + 1),
        )


@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.upsert_document_analysis")
@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.score_pod")
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.build_stop_aware_observations",
    return_value={"po_matches": {}},
)
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.derive_pod_scoring_observations",
    return_value={"delivery_signature_present": True},
)
@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.get_turvo_shipment")
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.resolve_graph_tenant_to_uuid",
    return_value=_TENANT_UUID,
)
def test_process_one_reuses_existing_extraction(
    mock_resolve,
    mock_turvo,
    mock_derive,
    mock_stop,
    mock_score,
    mock_upsert,
) -> None:
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "id": _SHIP_UUID,
        "shipment_number": "62762",
    }
    staging = MagicMock()
    staging.resolve_stored_pod_document.return_value = SimpleNamespace(
        storage_key="pod_attachments/x.pdf",
        document_id="doc-1",
    )
    mock_turvo.return_value = {
        "details": {
            "customId": "30389",
            "globalRoute": [],
            "startDate": {"date": "2026-01-01"},
            "endDate": {"date": "2026-01-02"},
        }
    }
    mock_score.return_value = PodScoreResult(
        final_score=87,
        max_score=100,
        pass_threshold=90,
        stops=[],
        needs_action=True,
    )
    mock_upsert.return_value = {"stored": True, "id": "da-score-1"}

    pages = [{"page_number": 1, "reference_ids": []}]
    svc = _service(shipments=shipments, staging=staging)
    with patch.object(
        svc,
        "_load_pod_extraction",
        return_value={"results": {"page_evidence": pages}, "document_id": "doc-1"},
    ):
        result = svc.process_one(
            tenant_slug="t3ra",
            shipment_id=_SHIP_UUID,
            use_existing_extraction=True,
        )

    assert result.success is True
    assert result.extraction_source == "existing"
    assert result.final_score == 87
    assert result.document_analysis_id == "da-score-1"
    mock_derive.assert_called_once_with(pages)
    mock_stop.assert_called_once()
    mock_upsert.assert_called_once()
    args, kwargs = mock_upsert.call_args
    assert args[0] == _SHIP_UUID
    assert args[1] == DocumentAnalysisType.POD_VS_TMS_ANALYSIS
    assert kwargs["confidence_score"] == 0.87
    mock_resolve.assert_called_once()


@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.run_pod_analysis")
@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.upsert_document_analysis")
@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.score_pod")
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.build_stop_aware_observations",
    return_value={},
)
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.derive_pod_scoring_observations",
    return_value={},
)
@patch("app.services.pod_lifecycle.pod_vs_tms_rescore_service.get_turvo_shipment")
@patch(
    "app.services.pod_lifecycle.pod_vs_tms_rescore_service.resolve_graph_tenant_to_uuid",
    return_value=_TENANT_UUID,
)
def test_process_one_reanalyzes_when_extraction_missing(
    mock_resolve,
    mock_turvo,
    mock_derive,
    mock_stop,
    mock_score,
    mock_upsert,
    mock_analysis,
) -> None:
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "id": _SHIP_UUID,
        "shipment_number": "62762",
    }
    staging = MagicMock()
    staging.resolve_stored_pod_document.return_value = SimpleNamespace(
        storage_key="pod_attachments/x.pdf",
        document_id="doc-1",
    )
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"settings": {}}
    mock_turvo.return_value = {"details": {"globalRoute": []}}
    pages = [{"page_number": 1}]
    mock_analysis.return_value = {
        "success": True,
        "document_id": "doc-1",
        "findings": {"pages": pages},
        "confidence_score": None,
    }
    mock_score.return_value = PodScoreResult(
        final_score=40,
        max_score=100,
        pass_threshold=90,
        stops=[],
        needs_action=True,
    )
    mock_upsert.side_effect = [
        {"stored": True, "id": "da-extract-1"},
        {"stored": True, "id": "da-score-1"},
    ]

    svc = _service(shipments=shipments, staging=staging, tenants=tenants)
    with patch.object(svc, "_load_pod_extraction", return_value=None):
        result = svc.process_one(
            tenant_slug="t3ra",
            shipment_id=_SHIP_UUID,
            use_existing_extraction=True,
        )

    assert result.success is True
    assert result.extraction_source == "reanalyzed"
    assert mock_upsert.call_count == 2
    first_type = mock_upsert.call_args_list[0].args[1]
    second_type = mock_upsert.call_args_list[1].args[1]
    assert first_type == DocumentAnalysisType.POD_EXTRACTION
    assert second_type == DocumentAnalysisType.POD_VS_TMS_ANALYSIS
    mock_analysis.assert_called_once()
    mock_resolve.assert_called_once()
    mock_derive.assert_called_once()
    mock_stop.assert_called_once()
