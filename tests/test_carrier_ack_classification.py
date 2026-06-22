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
    format_labeled_email_thread_for_llm,
    normalize_email_body_for_llm,
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
        "load_type": "ltl",
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


def test_build_email_thread_includes_sender_headers():
    messages = [
        {
            "content": "Could you create the BOL?",
            "direction": "inbound",
            "metadata": {"from": "vendor@x.com", "to": ["ana@gelita.com"]},
        },
    ]
    text = build_email_thread_llm_user_message(messages)
    assert text == (
        "email 1 [inbound | from: vendor@x.com | to: ana@gelita.com]\n"
        "Could you create the BOL?"
    )


def test_build_email_thread_outbound_sender_defaults_to_ops_rep():
    messages = [
        {
            "content": "Following up on the request. Thanks",
            "direction": "outbound",
            "metadata": {"to": ["vendor@x.com"]},
        },
    ]
    text = build_email_thread_llm_user_message(messages)
    assert text == (
        "email 1 [outbound | from: ops_rep | to: vendor@x.com]\n"
        "Following up on the request. Thanks"
    )


def test_format_labeled_email_thread_orders_and_labels():
    turns = [
        ({"direction": "outbound", "metadata": {"from": "a@g.com", "to": ["v@x.com"]}}, "Tender"),
        ({"direction": "inbound", "metadata": {"from": "v@x.com", "to": ["a@g.com"]}}, "We'll cover it"),
    ]
    text = format_labeled_email_thread_for_llm(turns)
    assert text == (
        "email 1 [outbound | from: a@g.com | to: v@x.com]\nTender\n\n"
        "email 2 [inbound | from: v@x.com | to: a@g.com]\nWe'll cover it"
    )


def test_normalize_email_body_strips_outlook_forward_html():
    html = (
        '<html><body><div class="elementToProof">Will do, thanks</div>'
        '<div id="appendonsend"></div><hr>'
        '<div id="divRplyFwdMsg"><b>From:</b> Ayush &lt;vendor@gmail.com&gt;'
        "<br><b>Sent:</b> 22 June 2026<br><b>Subject:</b> Re: tender</div>"
        "<div>i have r+l carriers assigned</div>"
        "</body></html>"
    )
    assert normalize_email_body_for_llm(body=html) == "Will do, thanks"


def test_normalize_email_body_keeps_forwarded_load_details_after_short_note():
    html = (
        '<html><body><div class="elementToProof"><br></div>'
        '<div style="font-family:Calibri">Howdy</div>'
        '<hr style="display:inline-block; width:98%">'
        '<div style="font-family:Calibri"><b>From:</b>&nbsp;tenant@x.com'
        "<br><b>Sent:</b>&nbsp;Monday, June 22, 2026 19:35"
        "<br><b>To:</b>&nbsp;vendor@x.com"
        "<br><b>Subject:</b>&nbsp;PICK UP REQUEST # 97088 </div>"
        "<p><b>Pickup address:</b><br>GELITA USA<br>SERGEANT BLUFF IA 51054</p>"
        "<p><b>Deliver to:</b><br>VIOBIN<br>MONTICELLO IL 61856</p>"
        "</body></html>"
    )
    text = normalize_email_body_for_llm(body=html)
    assert "Howdy" in text
    assert "Pickup address" in text
    assert "Deliver to" in text
    assert "VIOBIN" in text
    assert "From:" not in text
    assert "Sent:" not in text


def test_normalize_email_body_keeps_pure_forward_body_without_new_reply_text():
    html = (
        "<html><body><div class=\"elementToProof\"><br></div>"
        '<div id="appendonsend"></div><hr>'
        '<div id="divRplyFwdMsg"><b>From:</b> Ayush Kansal &lt;tenant@x.com&gt;'
        "<br><b>Sent:</b> 22 June 2026<br><b>Subject:</b> PICK UP REQUEST"
        "</div><div>Deliver to: CUSTOMER</div></body></html>"
    )
    assert normalize_email_body_for_llm(body=html) == "Deliver to: CUSTOMER"


def test_normalize_email_body_strips_inline_forward_plain():
    text = (
        "Will do, thanks From: Ayush <vendor@gmail.com> Sent: 22 June 2026 "
        "To: ops@tenant.com Subject: Re: tender I have R+L assigned"
    )
    assert normalize_email_body_for_llm(body=text) == "Will do, thanks"


def test_build_email_thread_keeps_forwarded_load_details_in_thread():
    messages = [
        {
            "content": (
                "<html><body><div class=\"elementToProof\"><br></div>"
                '<div style="font-family:Calibri">Howdy</div>'
                '<hr style="display:inline-block; width:98%">'
                '<div style="font-family:Calibri"><b>From:</b>&nbsp;tenant@x.com'
                "<br><b>Sent:</b>&nbsp;today<br><b>Subject:</b> tender</div>"
                "<div>Deliver to: CUSTOMER</div></body></html>"
            ),
            "direction": "inbound",
            "metadata": {"from": "vendor@x.com", "to": ["tenant@x.com"]},
        },
        {
            "content": "I have R+L carriers assigned, can you create the BOL?",
            "direction": "inbound",
            "metadata": {"from": "vendor@gmail.com", "to": ["vendor@x.com"]},
        },
    ]
    text = build_email_thread_llm_user_message(messages)
    assert "Howdy" in text
    assert "Deliver to: CUSTOMER" in text
    assert "I have R+L carriers assigned" in text


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
    render_variables = prompt_service.render_step.call_args.kwargs["variables"]
    assert render_variables == {"thread_text": thread_llm}
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
