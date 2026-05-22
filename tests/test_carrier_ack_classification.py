"""Tests for carrier ack LLM classification, router, and finalize node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.communications._mapper import (
    build_email_thread_llm_user_message,
    format_email_thread_for_llm,
)
from app.tools.gelita.email_parser import classify_carrier_acknowledgment
from app.utils.prompts import carrier_ack_system_prompt
from app.workflows.graph.routers import carrier_ack_router
from app.workflows.nodes.gelita.record_ack_received import (
    classify_carrier_ack,
    record_ack_received,
)

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _state(*, decision: str | None = None, **data_extra):
    data = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "tender_id": TENDER_UUID,
        "body": "We accept the load.",
    }
    if decision is not None:
        data["carrier_ack_decision"] = decision
    data.update(data_extra)
    return SimpleNamespace(tenant_id=TENANT_UUID, execution_id=RUN_UUID, data=data)


def test_format_email_thread_for_llm_numbering():
    text = format_email_thread_for_llm(["first", "second"])
    assert text == "email 1\nfirst\n\nemail 2\nsecond"


def test_build_email_thread_llm_user_message_from_communications_rows():
    messages = [
        {"content": "<p>Reminder</p>", "direction": "outbound"},
        {"content": "We accept the load.", "direction": "inbound"},
    ]
    text = build_email_thread_llm_user_message(
        messages,
        fallback_body="ignored",
    )
    assert "email 1" in text
    assert "email 2" in text
    assert "We accept the load." in text


def test_build_email_thread_llm_user_message_fallback_to_webhook():
    text = build_email_thread_llm_user_message(
        [],
        fallback_body="Confirmed.",
    )
    assert text == "Confirmed."


def test_classify_carrier_acknowledgment_empty_is_do_nothing():
    result = classify_carrier_acknowledgment(
        "", system_prompt=carrier_ack_system_prompt
    )
    assert result["decision"] == StatusSubType.DO_NOTHING.value


@patch("app.tools.gelita.email_parser.chat_json")
def test_classify_carrier_acknowledgment_parses_decision(mock_chat: MagicMock):
    mock_chat.return_value = {
        "decision": "rejected",
        "confidence": 0.9,
        "reason": "carrier declined",
    }
    result = classify_carrier_acknowledgment(
        "We cannot cover this load.",
        system_prompt=carrier_ack_system_prompt,
    )
    assert result["decision"] == StatusSubType.REJECTED.value


@patch("app.tools.gelita.email_parser.chat_json")
def test_classify_carrier_acknowledgment_legacy_boolean_accept(mock_chat: MagicMock):
    mock_chat.return_value = {
        "is_acknowledgment": True,
        "confidence": 0.8,
        "reason": "legacy",
    }
    result = classify_carrier_acknowledgment(
        "Confirmed.", system_prompt=carrier_ack_system_prompt
    )
    assert result["decision"] == StatusSubType.ACCEPTED.value


@pytest.mark.parametrize(
    ("decision", "expected_route"),
    [
        ("accepted", "accepted"),
        ("rejected", "rejected"),
        ("do_nothing", "do_nothing"),
        ("unknown", "do_nothing"),
        (None, "do_nothing"),
    ],
)
def test_carrier_ack_router(decision, expected_route):
    state = _state(decision=decision) if decision != "missing" else _state()
    if decision is None:
        state.data.pop("carrier_ack_decision", None)
    route = carrier_ack_router(state)
    assert route == expected_route


@patch(
    "app.workflows.nodes.gelita.record_ack_received.CommunicationsService"
)
@patch(
    "app.workflows.nodes.gelita.record_ack_received.classify_carrier_acknowledgment"
)
def test_classify_carrier_ack_node_sets_decision(
    mock_classify: MagicMock,
    mock_comm_svc_cls: MagicMock,
):
    mock_classify.return_value = {
        "decision": StatusSubType.ACCEPTED.value,
        "confidence": 1.0,
        "reason": "ok",
    }
    comm_svc = MagicMock()
    comm_svc.build_thread_llm_user_message.return_value = (
        "email 1\nWe accept the load.",
        1,
    )
    mock_comm_svc_cls.return_value = comm_svc

    state = _state(thread_id="thread-abc")
    out = classify_carrier_ack(state)
    comm_svc.build_thread_llm_user_message.assert_called_once()
    mock_classify.assert_called_once_with(
        "email 1\nWe accept the load.",
        system_prompt=carrier_ack_system_prompt,
    )
    assert out.data["carrier_ack_decision"] == StatusSubType.ACCEPTED.value
    assert out.data["carrier_ack_normalized_reply"] == "We accept the load."
    assert out.data["carrier_ack_thread_message_count"] == 1


@patch(
    "app.workflows.nodes.gelita.record_ack_received.CommunicationsService"
)
@patch(
    "app.workflows.nodes.gelita.record_ack_received.ActivityLogService"
)
@patch(
    "app.workflows.nodes.gelita.record_ack_received.classify_carrier_acknowledgment"
)
def test_classify_carrier_ack_records_llm_action_activity(
    mock_classify: MagicMock,
    mock_activity_svc_cls: MagicMock,
    mock_comm_svc_cls: MagicMock,
) -> None:
    llm_result = {
        "decision": StatusSubType.DO_NOTHING.value,
        "confidence": 0.6,
        "reason": "ambiguous reply",
    }
    mock_classify.return_value = llm_result
    comm_svc = MagicMock()
    comm_svc.build_thread_llm_user_message.return_value = (
        "email 1\nWe accept the load.",
        1,
    )
    mock_comm_svc_cls.return_value = comm_svc
    activity_log_service = MagicMock()
    activity_log_service.record_carrier_ack_llm_action.return_value = (
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )
    mock_activity_svc_cls.return_value = activity_log_service

    state = _state()
    out = classify_carrier_ack(state)

    activity_log_service.record_carrier_ack_llm_action.assert_called_once()
    call_kwargs = activity_log_service.record_carrier_ack_llm_action.call_args[1]
    assert call_kwargs["decision"] == StatusSubType.DO_NOTHING.value
    assert call_kwargs["workflow_lifecycle_id"] == LIFECYCLE_UUID
    assert call_kwargs["workflow_run_id"] == RUN_UUID
    assert call_kwargs["user_input"] == "We accept the load."
    assert call_kwargs["llm_output"] == llm_result
    assert out.data["carrier_ack_llm_activity_log_id"] == (
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )


@patch(
    "app.workflows.nodes.gelita.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_do_nothing_skips_activity(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.DO_NOTHING.value)
    record_ack_received(state)
    svc.apply_from_state.assert_called_once()
    kwargs = svc.apply_from_state.call_args[1]
    assert kwargs["to_status"] == StatusType.COMPLETED
    assert kwargs["to_sub_status"] == StatusSubType.DO_NOTHING
    assert kwargs["record_activity"] is False


@patch(
    "app.workflows.nodes.gelita.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_rejected_records_activity(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.REJECTED.value)
    record_ack_received(state)
    kwargs = svc.apply_from_state.call_args[1]
    assert kwargs["to_sub_status"] == StatusSubType.REJECTED
    assert kwargs["record_activity"] is True
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE


@patch(
    "app.workflows.nodes.gelita.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_accepted_records_activity(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.ACCEPTED.value)
    record_ack_received(state)
    kwargs = svc.apply_from_state.call_args[1]
    assert kwargs["to_sub_status"] == StatusSubType.ACCEPTED
    assert kwargs["record_activity"] is True
