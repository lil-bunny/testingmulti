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


def test_pod_analysis_display_fields_from_data() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "load_id": "30389",
            "pod_vs_ratecon_analysis_results": {
                "confidence_score": 0.876,
                "validation_summary": "Line 1 match.\nLine 2 delivery confirmed.",
                "overall_status": "PASS",
            },
        }
    )
    assert fields == PodAnalysisDisplayFields(
        load_id="30389",
        confidence_score="0.88",
        validation_summary="Line 1 match.\nLine 2 delivery confirmed.",
        overall_status="PASS",
    )


def test_pod_analysis_display_fields_from_shipment_custom_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "shipment": {"details": {"customId": "30389", "id": 1000324895}},
            "pod_vs_ratecon_analysis_results": {
                "confidence_score": 0.083,
                "validation_summary": "Mismatch on addresses.",
                "overall_status": "FAIL",
            },
        }
    )
    assert fields is not None
    assert fields.load_id == "30389"
    assert fields.overall_status == "FAIL"


def test_pod_analysis_display_fields_falls_back_to_shipment_id() -> None:
    fields = pod_analysis_display_fields_from_data(
        {
            "shipment_id": "1000324895",
            "pod_vs_ratecon_analysis_results": {
                "confidence_score": 0.5,
                "validation_summary": "OK",
                "overall_status": "UNKNOWN",
            },
        }
    )
    assert fields is not None
    assert fields.load_id == "1000324895"


def test_format_pod_analysis_title_and_facts() -> None:
    fields = PodAnalysisDisplayFields(
        load_id="30389",
        confidence_score="0.87",
        validation_summary="All fields matched.",
        overall_status="PASS",
    )
    assert format_pod_analysis_title("POD analyzed — Load {load_id}", fields=fields) == (
        "POD analyzed — Load 30389"
    )
    assert format_pod_analysis_body(None, fields=fields).startswith("Load 30389 POD score 0.87")
    facts = pod_analysis_facts(fields)
    assert facts[0] == ("Load ID", "30389")
    assert facts[1] == ("POD Score", "0.87")
    assert facts[2] == ("Status", "PASS")
    assert facts[3] == ("Summary", "All fields matched.")
