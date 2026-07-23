"""Tests for appointment scheduling confirmation reply domain helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from app.domain.appointment_scheduling.confirmation_reply import (
    DEFAULT_CONFIRMATION_REPLY_BODY,
    ConfirmationReplyDisplayFields,
    display_fields_from_data,
    parse_appointment_scheduling_confirmation_reply_settings,
    render_confirmation_reply,
    resolve_confirmation_reply_body,
)
from app.services.appointment_scheduling.email_service import (
    AppointmentSchedulingEmailService,
)

_STATE_DATA: dict[str, Any] = {
    "load_id": "62396",
    "reference_number": "DIAMOND-RPN00008809",
    "customer_name": "BUCHANAN CELLERS",
    "confirmed_delivery_at": "2026-07-18T10:30:00",
    "shipment_id": "turvo-123",
    "workflow_lifecycle_id": "11111111-2222-3333-4444-555555555555",
    "llm_scheduling_decision": {
        "selected_pickup_date": "07/01/2026",
        "calculated_delivery_date": "07/04/2026",
    },
}


def test_parse_appointment_scheduling_confirmation_reply_settings() -> None:
    settings = parse_appointment_scheduling_confirmation_reply_settings(
        {
            "appointment_scheduling": {
                "confirmation_reply": {
                    "template_html": "<p>Confirmed for {load_id}</p>",
                    "body_text": "plain fallback",
                },
            },
        }
    )
    assert settings is not None
    assert settings.template_html == "<p>Confirmed for {load_id}</p>"
    assert settings.body_text == "plain fallback"


def test_parse_returns_none_when_missing() -> None:
    assert parse_appointment_scheduling_confirmation_reply_settings(None) is None
    assert parse_appointment_scheduling_confirmation_reply_settings({}) is None
    assert (
        parse_appointment_scheduling_confirmation_reply_settings(
            {"appointment_scheduling": {}}
        )
        is None
    )


def test_display_fields_from_data() -> None:
    fields = display_fields_from_data(_STATE_DATA)
    assert fields == ConfirmationReplyDisplayFields(
        load_id="62396",
        reference_number="DIAMOND-RPN00008809",
        customer_name="BUCHANAN CELLERS",
        confirmed_delivery_at="2026-07-18T10:30:00",
        shipment_id="turvo-123",
        workflow_lifecycle_id="11111111-2222-3333-4444-555555555555",
        pickup_date="07/01/2026",
        delivery_date="2026-07-18T10:30:00",
    )


def test_render_confirmation_reply_substitutes_placeholders() -> None:
    fields = display_fields_from_data(_STATE_DATA)
    body = render_confirmation_reply(
        "Load {load_id} confirmed at {confirmed_delivery_at}",
        fields=fields,
    )
    assert body == "Load 62396 confirmed at 2026-07-18T10:30:00"


def test_render_confirmation_reply_missing_key_becomes_empty() -> None:
    fields = display_fields_from_data(_STATE_DATA)
    body = render_confirmation_reply(
        "Ref {reference_number} extra {unknown_key}",
        fields=fields,
    )
    assert body == "Ref DIAMOND-RPN00008809 extra "


def test_resolve_confirmation_reply_body_default_when_no_config() -> None:
    assert (
        resolve_confirmation_reply_body(None, _STATE_DATA)
        == DEFAULT_CONFIRMATION_REPLY_BODY
    )


def test_resolve_confirmation_reply_body_prefers_template_html() -> None:
    tenant_settings = {
        "appointment_scheduling": {
            "confirmation_reply": {
                "template_html": "<p>Confirmed {load_id}</p>",
                "body_text": "plain {load_id}",
            },
        },
    }
    assert resolve_confirmation_reply_body(tenant_settings, _STATE_DATA) == (
        "<p>Confirmed 62396</p>"
    )


def test_resolve_confirmation_reply_body_uses_body_text_when_no_html() -> None:
    tenant_settings = {
        "appointment_scheduling": {
            "confirmation_reply": {
                "body_text": "Confirmed load {load_id}, thanks",
            },
        },
    }
    assert resolve_confirmation_reply_body(tenant_settings, _STATE_DATA) == (
        "Confirmed load 62396, thanks"
    )


@dataclass
class _FakeState:
    tenant_id: str
    execution_id: str
    data: dict[str, Any]


def test_confirmation_email_service_uses_default_body() -> None:
    comms = MagicMock()
    comms.send_thread_reply.return_value = {"communication_id": "comm-1"}
    svc = AppointmentSchedulingEmailService(communications_service=comms)
    state = _FakeState(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={
            "thread_id": "thread-1",
            "tenant_settings": {},
            "mikey_account_id": {"account_id": "acc-1", "email_alias": "ops@example.com"},
        },
    )
    result = svc.send_confirmation_reply_from_state(state)
    assert result.sent is True
    comms.send_thread_reply.assert_called_once()
    assert comms.send_thread_reply.call_args.kwargs["body"] == DEFAULT_CONFIRMATION_REPLY_BODY


def test_confirmation_email_service_uses_tenant_html() -> None:
    comms = MagicMock()
    comms.send_thread_reply.return_value = {"communication_id": "comm-2"}
    svc = AppointmentSchedulingEmailService(communications_service=comms)
    state = _FakeState(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={
            **_STATE_DATA,
            "thread_id": "thread-1",
            "tenant_settings": {
                "appointment_scheduling": {
                    "confirmation_reply": {
                        "template_html": "<p>Thanks for load {load_id}</p>",
                    },
                },
            },
            "mikey_account_id": {"account_id": "acc-1", "email_alias": "ops@example.com"},
        },
    )
    result = svc.send_confirmation_reply_from_state(state)
    assert result.sent is True
    assert comms.send_thread_reply.call_args.kwargs["body"] == (
        "<p>Thanks for load 62396</p>"
    )
