"""Tests for carrier ack LLM classification, router, and finalize node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.prompt_step_keys import LOAD_TENDERING_CARRIER_ACK
from app.integrations.langsmith import MissingTenantPromptRefError
from app.integrations.langsmith.types import (
    PromptLoadMetadata,
    PromptTraceMetadata,
    RenderedPrompt,
)
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.communications._mapper import (
    build_email_thread_llm_user_message,
    format_email_thread_for_llm,
)
from app.tools.carrier_ack import classify_carrier_acknowledgment
from app.workflows.graph.routers import carrier_ack_router
from app.workflows.nodes.record_ack_received import (
    classify_carrier_ack,
    record_ack_received,
)

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMM_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

TEST_SYSTEM_PROMPT = "You classify carrier replies. Return JSON only."
TEST_PROMPT_REF = "carrier-ack-classify:production"


def _tenant_settings() -> dict:
    return {
        "prompts": {
            LOAD_TENDERING_CARRIER_ACK: TEST_PROMPT_REF,
        }
    }


def _state(*, decision: str | None = None, **data_extra):
    data = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "tender_id": TENDER_UUID,
        "body": "We accept the load.",
        "tenant_settings": _tenant_settings(),
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
        "", system_prompt=TEST_SYSTEM_PROMPT
    )
    assert result["decision"] == StatusSubType.DO_NOTHING.value


def test_classify_carrier_acknowledgment_missing_system_prompt():
    result = classify_carrier_acknowledgment(
        "Confirmed.",
        system_prompt="",
    )
    assert result["decision"] == StatusSubType.DO_NOTHING.value
    assert result["reason"] == "missing_tenant_prompt_configuration"


@patch("app.tools.carrier_ack.chat_json")
def test_classify_carrier_acknowledgment_parses_decision(mock_chat: MagicMock):
    mock_chat.return_value = {
        "decision": "rejected",
        "confidence": 0.9,
        "reason": "carrier declined",
    }
    result = classify_carrier_acknowledgment(
        "We cannot cover this load.",
        system_prompt=TEST_SYSTEM_PROMPT,
        user_prompt="email 1\nWe cannot cover this load.",
    )
    assert result["decision"] == StatusSubType.REJECTED.value
    mock_chat.assert_called_once_with(
        TEST_SYSTEM_PROMPT,
        "email 1\nWe cannot cover this load.",
        temperature=0.1,
        prompt_trace=None,
    )


@patch("app.tools.carrier_ack.chat_json")
def test_classify_carrier_acknowledgment_legacy_boolean_accept(mock_chat: MagicMock):
    mock_chat.return_value = {
        "is_acknowledgment": True,
        "confidence": 0.8,
        "reason": "legacy",
    }
    result = classify_carrier_acknowledgment(
        "Confirmed.", system_prompt=TEST_SYSTEM_PROMPT
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
    "app.workflows.nodes.record_ack_received.CommunicationsService"
)
@patch(
    "app.workflows.nodes.record_ack_received.PromptService"
)
@patch(
    "app.workflows.nodes.record_ack_received.classify_carrier_acknowledgment"
)
def test_classify_carrier_ack_node_sets_decision(
    mock_classify: MagicMock,
    mock_prompt_svc_cls: MagicMock,
    mock_comm_svc_cls: MagicMock,
):
    mock_classify.return_value = {
        "decision": StatusSubType.ACCEPTED.value,
        "confidence": 1.0,
        "reason": "ok",
    }
    thread_llm = "email 1\nWe accept the load."
    prompt_service = MagicMock()
    prompt_service.render_step.return_value = (
        RenderedPrompt(system=TEST_SYSTEM_PROMPT, user=thread_llm),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref=TEST_PROMPT_REF,
            commit_hash="deadbeef",
        ),
    )
    mock_prompt_svc_cls.return_value = prompt_service
    comm_svc = MagicMock()
    comm_svc.build_thread_llm_user_message.return_value = (thread_llm, 1)
    mock_comm_svc_cls.return_value = comm_svc

    state = _state(thread_id="thread-abc")
    out = classify_carrier_ack(state)
    comm_svc.build_thread_llm_user_message.assert_called_once()
    prompt_service.render_step.assert_called_once()
    mock_classify.assert_called_once_with(
        thread_llm,
        system_prompt=TEST_SYSTEM_PROMPT,
        user_prompt=thread_llm,
        prompt_trace=PromptTraceMetadata(
            prompt_step_key=LOAD_TENDERING_CARRIER_ACK,
            tenant_prompt_ref=TEST_PROMPT_REF,
            prompt_source="hub",
            prompt_commit_hash="deadbeef",
        ),
    )
    assert out.data["carrier_ack_decision"] == StatusSubType.ACCEPTED.value
    assert out.data["carrier_ack_normalized_reply"] == "We accept the load."
    assert out.data["carrier_ack_thread_message_count"] == 1


@patch(
    "app.workflows.nodes.record_ack_received.CommunicationsService"
)
@patch("app.workflows.nodes.record_ack_received.PromptService")
def test_classify_carrier_ack_missing_prompt_ref_fail_closed(
    mock_prompt_svc_cls: MagicMock,
    mock_comm_svc_cls: MagicMock,
) -> None:
    prompt_service = MagicMock()
    prompt_service.render_step.side_effect = MissingTenantPromptRefError("missing")
    mock_prompt_svc_cls.return_value = prompt_service
    comm_svc = MagicMock()
    comm_svc.build_thread_llm_user_message.return_value = (
        "email 1\nWe accept the load.",
        1,
    )
    mock_comm_svc_cls.return_value = comm_svc

    state = _state(thread_id="thread-abc", tenant_settings={"prompts": {}})
    out = classify_carrier_ack(state)
    assert out.data["carrier_ack_decision"] == StatusSubType.DO_NOTHING.value
    assert out.data["carrier_ack_reason"] == "missing_tenant_prompt_configuration"


@patch(
    "app.workflows.nodes.record_ack_received.CommunicationsService"
)
@patch(
    "app.workflows.nodes.record_ack_received.ActivityLogService"
)
@patch(
    "app.workflows.nodes.record_ack_received.PromptService"
)
@patch(
    "app.workflows.nodes.record_ack_received.classify_carrier_acknowledgment"
)
def test_classify_carrier_ack_records_llm_action_activity(
    mock_classify: MagicMock,
    mock_prompt_svc_cls: MagicMock,
    mock_activity_svc_cls: MagicMock,
    mock_comm_svc_cls: MagicMock,
) -> None:
    llm_result = {
        "decision": StatusSubType.DO_NOTHING.value,
        "confidence": 0.6,
        "reason": "ambiguous reply",
    }
    mock_classify.return_value = llm_result
    thread_llm = "email 1\nWe accept the load."
    prompt_service = MagicMock()
    prompt_service.render_step.return_value = (
        RenderedPrompt(system=TEST_SYSTEM_PROMPT, user=thread_llm),
        PromptLoadMetadata(
            source="fallback",
            tenant_prompt_ref=TEST_PROMPT_REF,
            commit_hash=None,
        ),
    )
    mock_prompt_svc_cls.return_value = prompt_service
    comm_svc = MagicMock()
    comm_svc.build_thread_llm_user_message.return_value = (thread_llm, 1)
    mock_comm_svc_cls.return_value = comm_svc
    activity_log_service = MagicMock()
    activity_log_service.record_action.return_value = (
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )
    mock_activity_svc_cls.return_value = activity_log_service

    state = _state(communication_id=COMM_UUID, thread_id="thread-abc")
    out = classify_carrier_ack(state)

    comm_svc.build_thread_llm_user_message.assert_called_once()
    activity_log_service.record_action.assert_called_once()
    write = activity_log_service.record_action.call_args[0][0]
    assert write.workflow_lifecycle_id == LIFECYCLE_UUID
    assert write.workflow_run_id == RUN_UUID
    assert write.communication_id == COMM_UUID
    assert write.metadata["carrier_ack_decision"] == StatusSubType.DO_NOTHING.value
    assert write.metadata["user_input"] == thread_llm
    assert write.metadata["output"] == llm_result
    assert write.metadata["prompt_step_key"] == LOAD_TENDERING_CARRIER_ACK
    assert write.metadata["tenant_prompt_ref"] == TEST_PROMPT_REF
    assert write.metadata["prompt_source"] == "fallback"
    assert write.metadata["prompt_commit_hash"] is None
    assert out.data["carrier_ack_llm_activity_log_id"] == (
        "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )


@patch(
    "app.workflows.nodes.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_do_nothing_skips_lifecycle(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.DO_NOTHING.value)
    out = record_ack_received(state)
    svc.apply_from_state.assert_not_called()
    assert "ack_recorded" not in out.data


@patch(
    "app.workflows.nodes.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_rejected_records_activity(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.REJECTED.value)
    record_ack_received(state)
    kwargs = svc.apply_from_state.call_args[1]
    assert kwargs["to_sub_status"] == StatusSubType.REJECTED
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE


@patch(
    "app.workflows.nodes.record_ack_received.LifecycleTransitionService"
)
def test_record_ack_received_accepted_records_activity(mock_svc_cls: MagicMock):
    svc = MagicMock()
    mock_svc_cls.return_value = svc
    state = _state(decision=StatusSubType.ACCEPTED.value)
    record_ack_received(state)
    kwargs = svc.apply_from_state.call_args[1]
    assert kwargs["to_sub_status"] == StatusSubType.ACCEPTED
