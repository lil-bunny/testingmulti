"""Tests for ``capture_turvo_shipment_snapshot`` and ``pod_scoring`` nodes."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.state import WorkflowState
from app.workflows.nodes.pod import capture_turvo_shipment_snapshot, pod_scoring

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_SINGLE_STOP_SHIPMENT = {
    "details": {
        "customId": "62762",
        "startDate": {"date": "2026-07-20T15:00:00Z"},
        "endDate": {"date": "2026-07-21T13:00:00Z"},
        "globalRoute": [
            {
                "stopType": {"key": "1500", "value": "Pickup"},
                "name": "Diamond Pet Foods - 95330 (Roth)",
                "address": {
                    "line1": "250 East Roth Road",
                    "city": "Lathrop",
                    "state": "CA",
                    "countryCode": "US",
                },
                "poNumbers": ["A1176371"],
                "notes": "Pallets: 37 | Weight: 40000",
            },
            {
                "stopType": {"key": "1501", "value": "Delivery"},
                "name": "COSTCO # 766",
                "address": {
                    "line1": "25900 HEATHER PLACE",
                    "city": "WILSONVILLE",
                    "state": "OR",
                    "countryCode": "US",
                },
                "poNumbers": ["007660706282"],
            },
        ],
    }
}

_MULTI_STOP_SHIPMENT = {
    "details": {
        "globalRoute": [
            {"stopType": {"key": "1500"}, "name": "A", "poNumbers": ["1"]},
            {"stopType": {"key": "1500"}, "name": "B", "poNumbers": ["2"]},
            {"stopType": {"key": "1501"}, "name": "C", "poNumbers": ["3"]},
        ]
    }
}


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
        data={"shipment_id": "SHP-001", "load_id": "LD-001", **data},
    )


def test_capture_turvo_shipment_snapshot_writes_dict_to_state() -> None:
    state = _state(shipment=_SINGLE_STOP_SHIPMENT)

    capture_turvo_shipment_snapshot(state)

    snapshot = state.data["turvo_shipment_snapshot"]
    assert snapshot["is_single_stop"] is True
    assert snapshot["pickup"]["name"] == "Diamond Pet Foods - 95330 (Roth)"
    assert len(snapshot["purchase_orders"]) == 2
    assert "error" not in state.data


def test_pod_scoring_multi_stop_bails_to_skip() -> None:
    state = _state(shipment=_MULTI_STOP_SHIPMENT)

    pod_scoring(state)

    assert state.data["pod_scoring_results"] == {
        "success": True,
        "skipped": True,
        "reason": "multi_stop_not_supported",
    }
    assert "error" not in state.data


@patch("app.workflows.nodes.pod.upsert_document_analysis")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_pod_scoring_persists_pod_vs_tms_analysis_row(mock_row, mock_upsert) -> None:
    from app.models.document_analysis import DocumentAnalysisType

    mock_upsert.return_value = {"stored": True, "id": "da-tms-1"}
    state = _state(
        shipment=_SINGLE_STOP_SHIPMENT,
        pod_analysis_results={
            "findings": {"pod_data": {"delivery_confirmed": True}},
            "document_id": "doc-1",
        },
        document_analysis_pod={"stored": True, "id": "da-1"},
    )
    state.data["pod_analysis_results"]["findings"]["pod_observations"] = {
        "delivery_signature_present": True,
        "extracted_reference_numbers": ["A1176371", "007660706282"],
    }

    pod_scoring(state)

    assert state.data["pod_scoring_results"]["success"] is True
    score = state.data["pod_scoring_results"]["score"]
    assert score["final_score"] == 100
    assert score["result"] == "PASS"

    mock_upsert.assert_called_once()
    args, kwargs = mock_upsert.call_args
    assert args[0] == "row-1"
    assert args[1] == DocumentAnalysisType.POD_VS_TMS_ANALYSIS
    assert kwargs["results"]["final_score"] == 100
    assert kwargs["results"]["result"] == "PASS"
    assert "pod_data" not in kwargs["results"]
    assert "pod_scoring" not in kwargs["results"]
    assert kwargs["confidence_score"] == 1.0
    assert kwargs.get("llm_model") is None
    assert state.data["document_analysis_pod_scoring"] == {
        "stored": True,
        "id": "da-tms-1",
    }

@patch("app.workflows.nodes.pod.upsert_document_analysis")
@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
def test_pod_scoring_skips_persist_when_extraction_not_stored(mock_row, mock_upsert) -> None:
    """No document_analysis_pod persist yet (e.g. manual soft-fail) -> do not upsert."""
    state = _state(
        shipment=_SINGLE_STOP_SHIPMENT,
        pod_analysis_results={"findings": {"pod_data": {}}},
    )

    pod_scoring(state)

    mock_upsert.assert_not_called()
    assert state.data["pod_scoring_results"]["success"] is True
    assert "error" not in state.data


def test_pod_scoring_no_pod_observations_scores_zero_and_does_not_crash() -> None:
    state = _state(shipment=_SINGLE_STOP_SHIPMENT)

    pod_scoring(state)

    score = state.data["pod_scoring_results"]["score"]
    assert score["final_score"] == 0
    assert score["result"] == "FAIL"
    assert "error" not in state.data
