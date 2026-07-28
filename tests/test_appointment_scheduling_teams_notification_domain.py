"""Tests for appointment scheduling draft-ready Teams notification domain helpers."""

from __future__ import annotations

from app.domain.appointment_scheduling.teams_notification import (
    AppointmentSchedulingDraftDisplayFields,
    display_fields_from_data,
    draft_ready_facts,
    format_draft_ready_body,
    format_draft_ready_title,
    parse_appointment_scheduling_teams_notification_settings,
)


def test_parse_appointment_scheduling_teams_notification_settings() -> None:
    settings = parse_appointment_scheduling_teams_notification_settings(
        {
            "appointment_scheduling": {
                "teams_notification": {
                    "teams_webhook_url": "https://example.invalid/webhook",
                    "message_title": "Draft ready — Load {load_id}",
                    "message_body": "Delivery {delivery_date}",
                },
            },
        }
    )
    assert settings is not None
    assert settings.teams_webhook_url.startswith("https://")
    assert settings.message_title == "Draft ready — Load {load_id}"


def test_display_fields_from_data() -> None:
    fields = display_fields_from_data(
        {
            "load_id": "62396",
            "reference_number": "DIAMOND-RPN00008809",
            "customer_name": "BUCHANAN CELLERS",
            "workflow_lifecycle_id": "11111111-2222-3333-4444-555555555555",
            "llm_appointment_decision": {
                "selected_pickup_date": "07/01/2026",
                "calculated_delivery_date": "07/04/2026",
            },
            "email_draft": {
                "to": "wh@example.com",
                "subject": 'DEL APPT REQ "62396"',
                "full_html": "<p>draft</p>",
            },
        }
    )
    assert fields == AppointmentSchedulingDraftDisplayFields(
        load_id="62396",
        reference_number="DIAMOND-RPN00008809",
        customer_name="BUCHANAN CELLERS",
        pickup_date="07/01/2026",
        delivery_date="07/04/2026",
        draft_subject='DEL APPT REQ "62396"',
        workflow_lifecycle_id="11111111-2222-3333-4444-555555555555",
    )


def test_display_fields_from_data_returns_none_when_draft_incomplete() -> None:
    assert display_fields_from_data({"load_id": "62396", "email_draft": {"to": "a@b.com"}}) is None


def test_format_draft_ready_title_body_and_facts() -> None:
    fields = AppointmentSchedulingDraftDisplayFields(
        load_id="62396",
        reference_number="DIAMOND-1",
        customer_name="Costco",
        pickup_date="07/01/2026",
        delivery_date="07/04/2026",
        draft_subject='DEL APPT REQ "62396"',
        workflow_lifecycle_id="wl-1",
    )
    assert format_draft_ready_title("Appointment draft ready — Load {load_id}", fields=fields) == (
        "Appointment draft ready — Load 62396"
    )
    assert "62396" in format_draft_ready_body(None, fields=fields)
    facts = draft_ready_facts(fields)
    assert facts[0] == ("Load ID", "62396")
    assert facts[-1] == ("Proposed delivery", "07/04/2026")
    fact_labels = [label for label, _ in facts]
    assert "Draft subject" not in fact_labels
    assert "Lifecycle ID" not in fact_labels


def test_display_fields_costco_includes_delivery_time_and_normalizes_iso_pickup() -> None:
    fields = display_fields_from_data(
        {
            "load_id": "30394",
            "reference_number": "DIAMOND-RPN00006732",
            "customer_name": "COSTCO #584 NW",
            "workflow_lifecycle_id": "wl-1",
            "llm_appointment_decision": {
                "selected_pickup_date": "2026-06-02",
                "selected_pickup_time": "08:00",
                "calculated_delivery_date": "06/03/2026",
                "calculated_delivery_weekday": "WEDNESDAY",
            },
            "email_draft": {
                "to": "wh@example.com",
                "subject": 'DEL APPT REQ "30394"',
                "full_html": "<p>draft</p>",
            },
        }
    )
    assert fields is not None
    assert fields.pickup_date == "06/02/2026"
    assert fields.pickup_time == "08:00"
    assert fields.delivery_time == "06:00"
    facts = draft_ready_facts(fields)
    assert facts[3] == ("Proposed pickup", "06/02/2026 · 08:00")
    assert facts[4] == ("Proposed delivery", "06/03/2026 · 06:00 (WEDNESDAY)")


def test_format_draft_ready_body_supports_delivery_display_placeholder() -> None:
    fields = AppointmentSchedulingDraftDisplayFields(
        load_id="30394",
        reference_number="REF",
        customer_name="COSTCO #584 NW",
        pickup_date="06/02/2026",
        delivery_date="06/03/2026",
        pickup_time="08:00",
        delivery_time="06:00",
        delivery_weekday="WEDNESDAY",
        draft_subject="subj",
        workflow_lifecycle_id="wl-1",
    )
    body = format_draft_ready_body(
        "Review in portal. Delivery {delivery_display}.",
        fields=fields,
    )
    assert body == "Review in portal. Delivery 06/03/2026 · 06:00 (WEDNESDAY)."
