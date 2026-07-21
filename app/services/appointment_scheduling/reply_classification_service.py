"""LLM classification for appointment scheduling customer-reply emails."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_customer_reply_llm_action,
)
from app.domain.prompt_step_keys import APPOINTMENT_SCHEDULING_CUSTOMER_REPLY
from app.integrations.langsmith import PromptTraceMetadata, PromptUnavailableError
from app.services.activity_log_service import ActivityLogService
from app.services.appointment_scheduling.lifecycle_service import (
    AppointmentSchedulingLifecycleService,
)
from app.services.communications.service import CommunicationsService
from app.services.prompt_service import (
    PromptService,
    resolve_appointment_scheduling_customer_reply_prompts,
)
from app.tools.appointment_scheduling.customer_reply import (
    DO_NOTHING,
    INSUFFICIENT,
    SUFFICIENT,
    build_customer_reply_result,
)
from app.tools.llm_client import LLMClientError, chat_json

logger = get_logger(__name__)


@dataclass
class AppointmentReplyClassificationResult:
    decision: str = DO_NOTHING
    reason: str = ""
    confidence: float = 0.0
    extracted_date: str | None = None
    extracted_time: str | None = None
    appointment_start_iso: str | None = None
    turvo_start_time: str | None = None
    thread_llm_input: str = ""
    thread_message_count: int = 0
    llm_raw: dict[str, Any] = field(default_factory=dict)
    llm_activity_log_id: str | None = None

    def to_state_patch(self) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "customer_reply_decision": self.decision,
            "customer_reply_reason": self.reason,
            "customer_reply_extraction": {
                "decision": self.decision,
                "confidence": self.confidence,
                "reason": self.reason,
                "extracted_date": self.extracted_date,
                "extracted_time": self.extracted_time,
                "appointment_start_iso": self.appointment_start_iso,
                "turvo_start_time": self.turvo_start_time,
            },
            "customer_reply_llm": self.llm_raw,
            "customer_reply_thread_llm_input": self.thread_llm_input,
            "customer_reply_thread_message_count": self.thread_message_count,
        }
        if self.appointment_start_iso:
            patch["confirmed_delivery_at"] = self.appointment_start_iso
        if self.llm_activity_log_id:
            patch["customer_reply_llm_activity_log_id"] = self.llm_activity_log_id
        return patch


class AppointmentReplyClassificationService:
    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
        prompt_service: PromptService | None = None,
        activity_log_service: ActivityLogService | None = None,
        lifecycle_service: AppointmentSchedulingLifecycleService | None = None,
    ) -> None:
        self._communications = communications_service or CommunicationsService()
        self._prompts = prompt_service or PromptService()
        self._activity = activity_log_service or ActivityLogService()
        self._lifecycle = lifecycle_service or AppointmentSchedulingLifecycleService()

    def classify_from_state(self, state) -> AppointmentReplyClassificationResult:
        tenant_id = (getattr(state, "tenant_id", None) or state.data.get("tenant_id") or "").strip()
        thread_id = str(state.data.get("thread_id") or "").strip()
        tenant_settings = state.data.get("tenant_settings") or {}
        return self.classify_from_payload(
            tenant_id=tenant_id,
            thread_id=thread_id,
            fallback_body=state.data.get("body"),
            tenant_settings=tenant_settings,
            workflow_lifecycle_id=str(state.data.get("workflow_lifecycle_id") or "").strip(),
            workflow_run_id=str(
                getattr(state, "execution_id", None) or state.data.get("execution_id") or ""
            ).strip(),
            communication_id=str(state.data.get("communication_id") or "").strip() or None,
        )

    def classify_from_payload(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        fallback_body: str | None,
        tenant_settings: dict[str, Any],
        workflow_lifecycle_id: str,
        workflow_run_id: str,
        communication_id: str | None = None,
    ) -> AppointmentReplyClassificationResult:
        reply_text = ""
        thread_message_count = 0
        if tenant_id and thread_id:
            draft_comm_id = None
            if workflow_lifecycle_id:
                draft_comm_id = self._lifecycle.draft_outbound_communication_id(
                    workflow_lifecycle_id
                )
            reply_text, thread_message_count = (
                self._communications.build_appointment_reply_thread_llm_user_message(
                    tenant_id,
                    thread_id,
                    draft_communication_id=draft_comm_id,
                    fallback_body=fallback_body,
                )
            )

        if not (reply_text or "").strip():
            return AppointmentReplyClassificationResult(
                decision=DO_NOTHING,
                reason="empty reply body",
                confidence=1.0,
                thread_llm_input=reply_text,
                thread_message_count=thread_message_count,
                llm_raw={
                    "decision": DO_NOTHING,
                    "confidence": 1.0,
                    "reason": "empty reply body",
                },
            )

        try:
            rendered, prompt_metadata = resolve_appointment_scheduling_customer_reply_prompts(
                tenant_settings,
                {"thread_text": reply_text},
                prompt_service=self._prompts,
            )
        except PromptUnavailableError as exc:
            logger.warning(
                "classify_customer_reply prompt unavailable lifecycle_id=%s: %s",
                workflow_lifecycle_id,
                exc,
            )
            return self._fail_closed(
                reply_text=reply_text,
                thread_message_count=thread_message_count,
                reason=str(exc),
            )

        prompt_trace = PromptTraceMetadata.from_load(
            APPOINTMENT_SCHEDULING_CUSTOMER_REPLY,
            prompt_metadata,
        )
        try:
            raw = chat_json(
                rendered.system,
                rendered.user or reply_text,
                temperature=0.1,
                prompt_trace=prompt_trace,
            )
        except LLMClientError as exc:
            logger.warning(
                "customer reply LLM failed lifecycle_id=%s: %s",
                workflow_lifecycle_id,
                exc,
            )
            return self._fail_closed(
                reply_text=reply_text,
                thread_message_count=thread_message_count,
                reason=f"llm_error: {exc}",
            )

        parsed = build_customer_reply_result(raw if isinstance(raw, dict) else {})
        result = AppointmentReplyClassificationResult(
            decision=parsed["decision"],
            reason=parsed["reason"],
            confidence=parsed["confidence"],
            extracted_date=parsed.get("extracted_date"),
            extracted_time=parsed.get("extracted_time"),
            appointment_start_iso=parsed.get("appointment_start_iso"),
            turvo_start_time=parsed.get("turvo_start_time"),
            thread_llm_input=reply_text,
            thread_message_count=thread_message_count,
            llm_raw=parsed,
        )

        if workflow_lifecycle_id and tenant_id and workflow_run_id:
            activity_metadata: dict[str, Any] = {
                "source": "classify_appointment_customer_reply",
                "customer_reply_decision": result.decision,
                "user_input": reply_text,
                "output": parsed,
                "prompt_step_key": APPOINTMENT_SCHEDULING_CUSTOMER_REPLY,
                "tenant_prompt_ref": prompt_metadata.tenant_prompt_ref,
                "prompt_source": prompt_metadata.source,
                "prompt_commit_hash": prompt_metadata.commit_hash,
            }
            activity_log_id = self._activity.record_action(
                ActivityLogWrite(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=workflow_lifecycle_id,
                    workflow_run_id=workflow_run_id,
                    description=format_customer_reply_llm_action(
                        decision=result.decision,
                        reason=result.reason,
                        confidence=result.confidence,
                    ),
                    communication_id=communication_id,
                    metadata=activity_metadata,
                )
            )
            if activity_log_id:
                result.llm_activity_log_id = activity_log_id

        return result

    @staticmethod
    def _fail_closed(
        *,
        reply_text: str,
        thread_message_count: int,
        reason: str,
    ) -> AppointmentReplyClassificationResult:
        return AppointmentReplyClassificationResult(
            decision=DO_NOTHING,
            reason=reason,
            confidence=0.0,
            thread_llm_input=reply_text,
            thread_message_count=thread_message_count,
            llm_raw={
                "decision": DO_NOTHING,
                "confidence": 0.0,
                "reason": reason,
            },
        )


__all__ = (
    "AppointmentReplyClassificationResult",
    "AppointmentReplyClassificationService",
    "SUFFICIENT",
    "INSUFFICIENT",
    "DO_NOTHING",
)
