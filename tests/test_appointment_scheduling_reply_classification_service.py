"""ReplyClassificationService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.lifecycle_transition import LifecycleTransitionResult
from app.services.appointment_scheduling.reply_classification_service import (
    ReplyClassificationService,
)
from app.tools.appointment_scheduling.customer_reply import (
    ACCEPTED,
    DO_NOTHING,
    REJECTED,
)

_TENANT = "tenant-1"
_LIFECYCLE = "lifecycle-1"
_RUN = "run-1"
_THREAD = "thread-1"


def _tenant_settings() -> dict:
    return {"prompts": {"appointment_scheduling": {"customer_reply": "appt-reply:staging"}}}


def _service(*, thread_text: str = "We can deliver July 18 at 10:30 AM") -> ReplyClassificationService:
    comms = MagicMock()
    comms.build_appointment_reply_thread_llm_user_message.return_value = (thread_text, 1)
    comms.find_outbound_draft_communication_id.return_value = None
    prompts = MagicMock()
    activity_deps = MagicMock()
    activity_deps.apply.return_value = LifecycleTransitionResult(
        lifecycle_updated=False,
        activity_log_id="activity-1",
        from_status=None,
        from_sub_status=None,
        to_status=None,
        to_sub_status=None,
    )
    return ReplyClassificationService(
        communications_service=comms,
        prompt_service=prompts,
        activity_deps=activity_deps,
    )


def test_classify_accepted_records_activity() -> None:
    svc = _service()
    llm_raw = {
        "decision": ACCEPTED,
        "confidence": 0.95,
        "reason": "explicit date and time",
        "extracted_date": "2026-07-18",
        "extracted_time": "10:30 AM",
    }
    with (
        patch(
            "app.services.appointment_scheduling.reply_classification_service.resolve_appointment_scheduling_customer_reply_prompts",
            return_value=(MagicMock(system="sys", user="user"), MagicMock()),
        ),
        patch(
            "app.services.appointment_scheduling.reply_classification_service.chat_json",
            return_value=llm_raw,
        ),
    ):
        result = svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body=llm_raw.get("extracted_date"),
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
            communication_id="comm-1",
        )

    assert result.decision == ACCEPTED
    assert result.appointment_start_iso == "2026-07-18T10:30:00"
    assert result.llm_activity_log_id == "activity-1"
    patch_data = result.to_state_patch()
    assert patch_data["confirmed_delivery_at"] == "2026-07-18T10:30:00"
    assert patch_data["customer_reply_extraction"]["reason"] == "explicit date and time"
    assert "customer_reply_reason" not in patch_data
    assert "customer_reply_llm_activity_log_id" not in patch_data
    svc._activity_deps.apply.assert_called_once()
    call_cmd = svc._activity_deps.apply.call_args.args[0]
    assert call_cmd.metadata is None
    assert "accepted" in call_cmd.description
    assert "0.95" in call_cmd.description


def test_classify_vague_reply_do_nothing() -> None:
    svc = _service(thread_text="Maybe next week sometime")
    llm_raw = {
        "decision": DO_NOTHING,
        "confidence": 0.8,
        "reason": "vague timing",
        "extracted_date": None,
        "extracted_time": None,
    }
    with (
        patch(
            "app.services.appointment_scheduling.reply_classification_service.resolve_appointment_scheduling_customer_reply_prompts",
            return_value=(MagicMock(system="sys", user="user"), MagicMock()),
        ),
        patch(
            "app.services.appointment_scheduling.reply_classification_service.chat_json",
            return_value=llm_raw,
        ),
    ):
        result = svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body="Maybe next week",
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
        )

    assert result.decision == DO_NOTHING
    svc._activity_deps.apply.assert_called_once()
    patch_data = result.to_state_patch()
    assert patch_data["customer_reply_decision"] == DO_NOTHING
    assert patch_data["customer_reply_extraction"]["reason"] == llm_raw["reason"]
    assert "customer_reply_reason" not in patch_data
    assert "customer_reply_llm_activity_log_id" not in patch_data
    assert "customer_reply_llm" not in patch_data
    assert "customer_reply_thread_llm_input" not in patch_data
    assert "customer_reply_thread_message_count" not in patch_data
    assert "confirmed_delivery_at" not in patch_data


def test_classify_rejected_records_activity() -> None:
    svc = _service(thread_text="Can we do next day at 4pm?")
    llm_raw = {
        "decision": REJECTED,
        "confidence": 0.85,
        "reason": "counter-proposal",
        "extracted_date": None,
        "extracted_time": "16:00",
    }
    with (
        patch(
            "app.services.appointment_scheduling.reply_classification_service.resolve_appointment_scheduling_customer_reply_prompts",
            return_value=(MagicMock(system="sys", user="user"), MagicMock()),
        ),
        patch(
            "app.services.appointment_scheduling.reply_classification_service.chat_json",
            return_value=llm_raw,
        ),
    ):
        result = svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body="Can we do next day at 4pm?",
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
        )

    assert result.decision == REJECTED
    assert "confirmed_delivery_at" not in result.to_state_patch()


def test_classify_empty_body_do_nothing() -> None:
    svc = _service(thread_text="")
    svc._communications.build_appointment_reply_thread_llm_user_message.return_value = ("", 0)
    result = svc.classify_from_payload(
        tenant_id=_TENANT,
        thread_id=_THREAD,
        fallback_body="",
        tenant_settings=_tenant_settings(),
        workflow_lifecycle_id=_LIFECYCLE,
        workflow_run_id=_RUN,
    )
    assert result.decision == DO_NOTHING
    svc._activity_deps.apply.assert_not_called()


def test_classify_from_state() -> None:
    svc = _service()
    state = SimpleNamespace(
        tenant_id=_TENANT,
        execution_id=_RUN,
        data={
            "thread_id": _THREAD,
            "tenant_settings": _tenant_settings(),
            "workflow_lifecycle_id": _LIFECYCLE,
            "body": "July 18 10:30 AM",
        },
    )
    with patch.object(svc, "classify_from_payload", return_value=MagicMock(to_state_patch=lambda: {"customer_reply_decision": ACCEPTED})) as mock:
        svc.classify_from_state(state)
    mock.assert_called_once()


def test_classify_passes_lifecycle_draft_comm_to_comms_builder() -> None:
    svc = _service()
    svc._communications.find_outbound_draft_communication_id.return_value = "draft-comm-1"
    llm_raw = {
        "decision": DO_NOTHING,
        "confidence": 0.5,
        "reason": "time only",
        "extracted_date": None,
        "extracted_time": "17:00",
    }
    with (
        patch(
            "app.services.appointment_scheduling.reply_classification_service.resolve_appointment_scheduling_customer_reply_prompts",
            return_value=(MagicMock(system="sys", user="user"), MagicMock()),
        ),
        patch(
            "app.services.appointment_scheduling.reply_classification_service.chat_json",
            return_value=llm_raw,
        ),
    ):
        svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body="5PM",
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
        )

    svc._communications.find_outbound_draft_communication_id.assert_called_once_with(
        tenant_id=_TENANT,
        workflow_lifecycle_id=_LIFECYCLE,
    )
    svc._communications.build_appointment_reply_thread_llm_user_message.assert_called_once_with(
        _TENANT,
        _THREAD,
        draft_communication_id="draft-comm-1",
        fallback_body="5PM",
    )
