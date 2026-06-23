"""DriverDetailsClassificationService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.prompt_step_keys import DRIVER_ASSIGNMENT_DRIVER_DETAILS
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.driver_details_classification_service import (
    DriverDetailsClassificationService,
)
from app.tools.driver_details import DO_NOTHING, HAS_DETAILS

_TENANT = "tenant-1"
_LIFECYCLE = "lifecycle-1"
_RUN = "run-1"
_THREAD = "thread-1"


def _tenant_settings() -> dict:
    return {
        "prompts": {
            DRIVER_ASSIGNMENT_DRIVER_DETAILS: "driver-details-extract:staging",
        }
    }


def _service(
    *,
    thread_text: str = "email 1\nDriver John 555-0100",
    llm_raw: dict | None = None,
) -> DriverDetailsClassificationService:
    comms = MagicMock()
    comms.build_thread_llm_user_message.return_value = (thread_text, 1)
    prompts = MagicMock()
    prompts.render_step.return_value = (
        RenderedPrompt(system="extract driver", user=None),
        PromptLoadMetadata(
            tenant_prompt_ref="driver-details-extract:staging",
            source="fallback",
            commit_hash="abc",
        ),
    )
    activity = MagicMock()
    activity.record_action.return_value = "activity-1"
    svc = DriverDetailsClassificationService(
        communications_service=comms,
        prompt_service=prompts,
        activity_log_service=activity,
    )
    return svc


def test_classify_from_payload_has_details() -> None:
    svc = _service()
    llm_raw = {
        "decision": HAS_DETAILS,
        "confidence": 0.9,
        "reason": "complete",
        "driver": {"name": "John", "phone": "555-0100", "email": None},
    }
    with patch(
        "app.services.driver_details_classification_service.chat_json",
        return_value=llm_raw,
    ):
        result = svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body="Driver John 555-0100",
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
            communication_id="comm-1",
            shipment_id="ship-1",
        )

    assert result.decision == HAS_DETAILS
    assert result.driver["name"] == "John"
    assert result.llm_activity_log_id == "activity-1"
    patch_data = result.to_state_patch()
    assert patch_data["driver_details_decision"] == HAS_DETAILS


def test_classify_from_payload_empty_body_do_nothing() -> None:
    svc = _service(thread_text="")
    svc._communications.build_thread_llm_user_message.return_value = ("", 0)
    result = svc.classify_from_payload(
        tenant_id=_TENANT,
        thread_id=_THREAD,
        fallback_body="   ",
        tenant_settings=_tenant_settings(),
        workflow_lifecycle_id=_LIFECYCLE,
        workflow_run_id=_RUN,
    )
    assert result.decision == DO_NOTHING
    assert result.reason == "empty reply body"


def test_classify_from_payload_llm_error_fail_closed() -> None:
    from app.tools.llm_client import LLMClientError

    svc = _service()
    with patch(
        "app.services.driver_details_classification_service.chat_json",
        side_effect=LLMClientError("timeout"),
    ):
        result = svc.classify_from_payload(
            tenant_id=_TENANT,
            thread_id=_THREAD,
            fallback_body="Driver info",
            tenant_settings=_tenant_settings(),
            workflow_lifecycle_id=_LIFECYCLE,
            workflow_run_id=_RUN,
        )
    assert result.decision == DO_NOTHING
    assert "llm_error" in result.reason
