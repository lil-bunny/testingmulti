"""Tests for POD analysis Teams notification domain helpers."""

from __future__ import annotations

from dataclasses import asdict

from app.integrations.turvo.pod_inputs import (
    TurvoPurchaseOrder,
    TurvoShipmentPodInputs,
    TurvoStop,
)
from app.services.pod_lifecycle.pod_scoring import score_pod

from app.domain.pod_lifecycle.teams_notification import (
    PodAnalysisDisplayFields,
    format_pod_analysis_body,
    format_pod_analysis_title,
    parse_pod_teams_notification_settings,
    pod_analysis_display_fields_from_data,
    pod_analysis_facts,
)


def test_parse_pod_teams_notification_settings() -> None:
    settings = parse_pod_teams_notification_settings(
        {
            "pod_lifecycle": {
                "teams_notification": {
                    "teams_webhook_url": "https://example.invalid/webhook",
                    "message_title": "POD — Load {load_id}",
                    "message_body": "Score {confidence_score}",
                },
            },
        }
    )
    assert settings is not None
    assert settings.teams_webhook_url.startswith("https://")
    assert settings.message_title == "POD — Load {load_id}"


def _scoring_results(*, final_score: float, stops: list | None = None) -> dict:
    return {
        "success": True,
        "score": {
            "final_score": final_score,
            "max_score": 100,
            "pass_threshold": 90,
            "stops": stops if stops is not None else [],
        },
    }


def test_pod_analysis_display_fields_from_data() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "load_id": "30389",
            "pod_scoring_results": _scoring_results(
                final_score=88,
                stops=[
                    {
                        "stop_type": "pickup",
                        "stop_order": 1,
                        "fields": [
                            {
                                "label": "reference_id",
                                "category": "identity",
                                "score": 20,
                                "max_score": 20,
                                "comparisons": [
                                    {"po_number": "PO1", "matched": True, "source": "PO1", "target": "PO1"}
                                ],
                            },
                        ],
                    },
                    {
                        "stop_type": "delivery",
                        "stop_order": 2,
                        "fields": [
                            {
                                "label": "signature",
                                "category": "identity",
                                "score": 60,
                                "max_score": 60,
                                "remark": "Present.",
                            },
                            {
                                "label": "reference_id",
                                "category": "identity",
                                "score": 20,
                                "max_score": 20,
                                "comparisons": [
                                    {"po_number": "PO2", "matched": True, "source": "PO2", "target": "PO2"}
                                ],
                            },
                        ],
                    },
                ],
            ),
        }
    )
    assert fields == PodAnalysisDisplayFields(
        load_id="30389",
        score="88/100",
        review_summary=(
            "pickup ref-id 20/20 (1/1 POs); "
            "signature 60/60; delivery ref-id 20/20 (1/1 POs)"
        ),
        overall_status="FAIL",
    )


def test_display_fields_read_real_score_pod_output() -> None:
    """Guard the ``PodScoreResult`` field names the Teams card reads."""
    pod_inputs = TurvoShipmentPodInputs(
        is_single_stop=True,
        pickup=TurvoStop(name="Shipper", address="1 A St, Lathrop, CA, US"),
        delivery=TurvoStop(name="Consignee", address="2 B St, Wilsonville, OR, US"),
        purchase_orders=[
            TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup"),
            TurvoPurchaseOrder(po_number="007660706282", stop_type="delivery"),
        ],
        pickup_date="2026-07-20T15:00:00Z",
        delivery_date="2026-07-21T13:00:00Z",
        ordered_pallet_qty=37,
        custom_id="30397",
    )
    score = score_pod(
        {
            "delivery_signature_present": True,
            "extracted_reference_numbers": ["A1176371", "007660706282"],
        },
        pod_inputs,
    )

    fields = pod_analysis_display_fields_from_data(
        {
            "load_id": "30397",
            "pod_scoring_results": {"success": True, "score": asdict(score)},
        }
    )

    assert fields is not None
    assert fields.score == "100/100"
    assert fields.overall_status == "PASS"


def test_pod_analysis_display_fields_from_shipment_custom_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "shipment": {"details": {"customId": "30389", "id": 1000324895}},
            "pod_scoring_results": _scoring_results(final_score=8),
        }
    )
    assert fields is not None
    assert fields.load_id == "30389"
    assert fields.overall_status == "FAIL"


def test_pod_analysis_display_fields_falls_back_to_shipment_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "pod_scoring_results": _scoring_results(final_score=50),
        }
    )
    assert fields is not None
    assert fields.load_id == "1000324895"


def test_pod_analysis_display_fields_none_when_skipped() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "load_id": "30389",
            "pod_scoring_results": {"success": True, "skipped": True, "reason": "multi_stop_not_supported"},
        }
    )
    assert fields is None


def test_format_pod_analysis_title_and_facts() -> None:
    fields = PodAnalysisDisplayFields(
        load_id="30389",
        score="87/100",
        review_summary="All fields matched.",
        overall_status="PASS",
    )
    assert format_pod_analysis_title("POD analyzed — Load {load_id}", fields=fields) == (
        "POD analyzed — Load 30389"
    )
    assert format_pod_analysis_body(None, fields=fields).startswith("Load 30389 POD score 87/100")
    facts = pod_analysis_facts(fields)
    assert facts[0] == ("Load ID", "30389")
    assert facts[1] == ("POD Score", "87/100")
    assert facts[2] == ("Status", "PASS")
    assert facts[3] == ("Review summary", "All fields matched.")
