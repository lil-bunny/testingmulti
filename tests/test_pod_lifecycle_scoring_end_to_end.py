"""In-process PoD scoring chain against the sample Turvo shipment fixture.

Drives ``pod_analysis`` → ``pod_scoring`` with
stubbed LLM output against ``scripts/pod-scoring-model-v2/shipments.json``
(guards Turvo schema drift). Live webhook/Celery e2e lives under ``tests/e2e/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.domain.state import WorkflowState
from app.workflows.nodes.pod import pod_scoring

_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "pod-scoring-model-v2"
    / "shipments.json"
)

TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_PICKUP_PO = "A1176371"
_DELIVERY_PO = "007660706282"


def _load_sample_shipment() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
        data={"shipment_id": "62762", "shipments_row_id": "row-1", **data},
    )


def _fake_raw_llm_response() -> dict:
    return {
        "pages": [
            {
                "page_number": 1,
                "proof_of_receipt": {
                    "has_receiver_signature": True,
                    "has_stamp": False,
                    "has_delivery_sticker": False,
                },
                "signature_owner": "receiver",
                "fields": [
                    {"key": "pickup_address", "value": "250 East Roth Road, Lathrop, CA, US"},
                    {"key": "destination_address", "value": "25900 HEATHER PLACE, WILSONVILLE, OR, US"},
                ],
                "reference_ids": [
                    {"label": "PO#", "value": _PICKUP_PO},
                    {"label": "Customer PO#", "value": _DELIVERY_PO},
                ],
                "pallets_shipped": 37,
                "damage_detected": False,
                "damage_detail": None,
            }
        ]
    }


def _fake_final_pod_data() -> dict:
    return {
        "delivery_confirmed": True,
        "pickup_location": "Diamond Pet Foods - 95330 (Roth)",
        "pickup_address": "250 East Roth Road, Lathrop, CA, US",
        "destination_location": "COSTCO # 766",
        "destination_address": "25900 HEATHER PLACE, WILSONVILLE, OR, US",
        "stop_times": [],
    }


@patch("app.tools.pod.extract_pod_from_pdf_path")
@patch("app.tools.pod.resolve_merged_pod_object_key")
def _run_pod_analysis(mock_resolve, mock_extract, *, shipment_payload: dict, tmp_path) -> dict:
    from app.tools.pod import pod_analysis

    merged = tmp_path / "pod_62762.pdf"
    merged.write_bytes(b"%PDF-1.4 stub")
    mock_resolve.return_value = ("pod_attachments/merged.pdf", {"source": "state"})
    mock_extract.return_value = (
        [{"extracted_data": {"page": 1}, "error": None}],
        _fake_final_pod_data(),
        [],
        [],
        _fake_raw_llm_response(),
    )

    out = pod_analysis(
        {
            "shipment_id": "62762",
            "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
            "pod_merged_local_path": str(merged),
            "documents_pod": {"id": "doc-1"},
            "shipment": shipment_payload,
        }
    )
    assert out["success"] is True

    mock_extract.assert_called_once()
    assert mock_extract.call_args.kwargs["broker_name"] == "Bajwa Truckers Inc"

    return out


@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
@patch("app.workflows.nodes.pod.upsert_document_analysis")
def test_pod_lifecycle_scoring_passes_for_real_sample_shipment(
    mock_upsert, mock_row_id, tmp_path
) -> None:
    """Both PO numbers resolve to and match their own Turvo stops -> 100."""
    mock_upsert.return_value = {"stored": True, "id": "da-1"}
    shipment_payload = _load_sample_shipment()

    pod_analysis_results = _run_pod_analysis(
        shipment_payload=shipment_payload, tmp_path=tmp_path
    )

    state = _state(
        shipment=shipment_payload,
        pod_analysis_results=pod_analysis_results,
        pod_analysis_stored=True,
        pod_analysis_id="da-1",
    )

    pod_scoring(state)

    score = state.data["pod_scoring_results"]["score"]
    assert score["final_score"] == 100
    assert score["needs_action"] is True
    assert score["overall_status"] == "PASS"
    assert len(score["po_scores"]) == 2

    mock_upsert.assert_called_once()
    args, kwargs = mock_upsert.call_args
    from app.models.document_analysis import DocumentAnalysisType

    assert args[1] == DocumentAnalysisType.POD_VS_TMS_ANALYSIS
    assert kwargs["results"]["final_score"] == 100
    assert "result" not in kwargs["results"]
    assert "pod_scoring" not in kwargs["results"]
    assert kwargs["confidence_score"] == 1.0
    assert kwargs.get("llm_model") is None
    assert "document_analysis_pod_scoring" not in state.data


@patch("app.workflows.nodes.pod.resolve_shipments_row_id_for_db", return_value="row-1")
@patch("app.workflows.nodes.pod.upsert_document_analysis")
def test_pod_lifecycle_scoring_fails_without_delivery_signature(
    mock_upsert, mock_row_id, tmp_path
) -> None:
    """No delivery signature zeros the signature component; ref-id still scores 40."""
    mock_upsert.return_value = {"stored": True, "id": "da-1"}
    shipment_payload = _load_sample_shipment()

    with patch("app.tools.pod.extract_pod_from_pdf_path") as mock_extract, patch(
        "app.tools.pod.resolve_merged_pod_object_key"
    ) as mock_resolve:
        merged = tmp_path / "pod_62762.pdf"
        merged.write_bytes(b"%PDF-1.4 stub")
        mock_resolve.return_value = ("pod_attachments/merged.pdf", {"source": "state"})
        no_signature_response = _fake_raw_llm_response()
        no_signature_response["pages"][0]["proof_of_receipt"]["has_receiver_signature"] = False
        mock_extract.return_value = (
            [{"extracted_data": {"page": 1}, "error": None}],
            _fake_final_pod_data(),
            [],
            [],
            no_signature_response,
        )

        from app.tools.pod import pod_analysis

        pod_analysis_results = pod_analysis(
            {
                "shipment_id": "62762",
                "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
                "pod_merged_local_path": str(merged),
                "documents_pod": {"id": "doc-1"},
                "shipment": shipment_payload,
            }
        )

    state = _state(
        shipment=shipment_payload,
        pod_analysis_results=pod_analysis_results,
        pod_analysis_stored=True,
        pod_analysis_id="da-1",
    )

    pod_scoring(state)

    score = state.data["pod_scoring_results"]["score"]
    assert score["final_score"] == 40
    assert score["signature"]["score"] == 0
    assert score["needs_action"] is True
    assert score["overall_status"] == "FAIL"
    mock_upsert.assert_called_once()
