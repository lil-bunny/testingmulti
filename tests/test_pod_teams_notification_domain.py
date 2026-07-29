"""Tests for POD analysis Teams notification domain helpers."""

from __future__ import annotations

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


def _scoring_results(*, final_score: float, result: str, po_scores: list | None = None) -> dict:
    return {
        "success": True,
        "score": {
            "final_score": final_score,
            "result": result,
            "po_scores": po_scores if po_scores is not None else [],
            "exceptions": [],
            "remarks": [],
        },
    }


def test_pod_analysis_display_fields_from_data() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "load_id": "30389",
            "pod_scoring_results": _scoring_results(
                final_score=88,
                result="PASS",
                po_scores=[{"po_number": "A1176371", "po_total": 88}],
            ),
        }
    )
    assert fields == PodAnalysisDisplayFields(
        load_id="30389",
        confidence_score="88/100",
        validation_summary="A1176371: 88/100",
        overall_status="PASS",
    )


def test_pod_analysis_display_fields_from_shipment_custom_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "shipment": {"details": {"customId": "30389", "id": 1000324895}},
            "pod_scoring_results": _scoring_results(final_score=8, result="FAIL"),
        }
    )
    assert fields is not None
    assert fields.load_id == "30389"
    assert fields.overall_status == "FAIL"


def test_pod_analysis_display_fields_falls_back_to_shipment_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "pod_scoring_results": _scoring_results(final_score=50, result="FAIL"),
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
        confidence_score="87/100",
        validation_summary="All fields matched.",
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
    assert facts[3] == ("Summary", "All fields matched.")
