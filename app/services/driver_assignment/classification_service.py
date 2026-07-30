"""LLM classification for driver-details email replies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logger import get_logger
from app.domain.driver_assignment.activity_log_descriptions import format_driver_details_llm_action
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.prompt_step_keys import DRIVER_ASSIGNMENT_DRIVER_DETAILS
from app.integrations.langsmith import (
    MissingTenantPromptRefError,
    PromptTraceMetadata,
    PromptUnavailableError,
)
from app.services.activity_log_service import ActivityLogService
from app.services.communications.service import CommunicationsService
from app.services.prompt_service import PromptService
from app.tools.driver_details import (
    DO_NOTHING,
    build_driver_details_result,
    normalize_driver_reply_body,
)
from app.tools.llm_credentials import resolve_llm_credentials
from app.tools.llm_client import LLMClientError, chat_json

logger = get_logger(__name__)


@dataclass
class DriverDetailsClassificationResult:
    decision: str = DO_NOTHING
    reason: str = ""
    confidence: float = 0.0
    driver: dict[str, str | None] = field(default_factory=dict)
    thread_llm_input: str = ""
    normalized_reply: str = ""
    thread_message_count: int = 0
    llm_raw: dict[str, Any] = field(default_factory=dict)
    llm_activity_log_id: str | None = None

    def to_state_patch(self) -> dict[str, Any]:
        """State keys consumed by routers / TMS; LLM audit lives on activity_logs."""
        patch: dict[str, Any] = {
            "driver_details_decision": self.decision,
            "driver_details_extraction": {
                "decision": self.decision,
                "confidence": self.confidence,
                "reason": self.reason,
                "driver": self.driver,
            },
        }
        if self.llm_activity_log_id:
            patch["driver_details_llm_activity_log_id"] = self.llm_activity_log_id
        return patch


class DriverDetailsClassificationService:
    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
        prompt_service: PromptService | None = None,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self._communications = communications_service or CommunicationsService()
        self._prompts = prompt_service or PromptService()
        self._activity = activity_log_service or ActivityLogService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def classify_from_state(self, state) -> DriverDetailsClassificationResult:
        tenant_id = (getattr(state, "tenant_id", None) or state.data.get("tenant_id") or "").strip()
        thread_id = str(state.data.get("thread_id") or "").strip()
        fallback_body = state.data.get("body")
        tenant_settings = state.data.get("tenant_settings") or {}
        return self.classify_from_payload(
            tenant_id=tenant_id,
            thread_id=thread_id,
            fallback_body=fallback_body,
            tenant_settings=tenant_settings,
            workflow_lifecycle_id=str(state.data.get("workflow_lifecycle_id") or "").strip(),
            workflow_run_id=str(
                getattr(state, "execution_id", None) or state.data.get("execution_id") or ""
            ).strip(),
            communication_id=self._clean(state.data.get("communication_id")),
            shipment_id=self._clean(state.data.get("shipment_id")),
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
        shipment_id: str | None = None,
    ) -> DriverDetailsClassificationResult:
        latest_reply = normalize_driver_reply_body(body=fallback_body)
        reply_text = latest_reply
        thread_message_count = 0
        if tenant_id and thread_id:
            reply_text, thread_message_count = (
                self._communications.build_thread_llm_user_message(
                    tenant_id,
                    thread_id,
                    fallback_body=fallback_body,
                )
            )

        if not (reply_text or "").strip():
            return DriverDetailsClassificationResult(
                decision=DO_NOTHING,
                reason="empty reply body",
                confidence=1.0,
                normalized_reply=latest_reply,
                thread_llm_input=reply_text,
                thread_message_count=thread_message_count,
                llm_raw={
                    "decision": DO_NOTHING,
                    "confidence": 1.0,
                    "reason": "empty reply body",
                    "driver": {"name": None, "phone": None, "email": None},
                },
            )

        try:
            rendered, prompt_metadata = self._prompts.render_step(
                tenant_settings=tenant_settings,
                prompt_step_key=DRIVER_ASSIGNMENT_DRIVER_DETAILS,
                variables={"thread_text": reply_text},
            )
        except (MissingTenantPromptRefError, PromptUnavailableError) as exc:
            logger.warning(
                "classify_driver_details prompt unavailable lifecycle_id=%s: %s",
                workflow_lifecycle_id,
                exc,
            )
            return self._fail_closed(
                latest_reply=latest_reply,
                reply_text=reply_text,
                thread_message_count=thread_message_count,
                reason=str(exc),
            )

        prompt_trace = PromptTraceMetadata.from_load(
            DRIVER_ASSIGNMENT_DRIVER_DETAILS,
            prompt_metadata,
        )
        credentials = resolve_llm_credentials(workflow_name="driver_assignment")
        try:
            raw = chat_json(
                rendered.system,
                rendered.user or reply_text,
                credentials=credentials,
                temperature=0.1,
                prompt_trace=prompt_trace,
            )
        except LLMClientError as exc:
            logger.warning(
                "driver details LLM failed lifecycle_id=%s: %s",
                workflow_lifecycle_id,
                exc,
            )
            return self._fail_closed(
                latest_reply=latest_reply,
                reply_text=reply_text,
                thread_message_count=thread_message_count,
                reason=f"llm_error: {exc}",
            )

        parsed = build_driver_details_result(raw if isinstance(raw, dict) else {})
        result = DriverDetailsClassificationResult(
            decision=parsed["decision"],
            reason=parsed["reason"],
            confidence=parsed["confidence"],
            driver=parsed["driver"],
            normalized_reply=latest_reply,
            thread_llm_input=reply_text,
            thread_message_count=thread_message_count,
            llm_raw=parsed,
        )

        if workflow_lifecycle_id and tenant_id and workflow_run_id:
            activity_metadata: dict[str, Any] = {
                "source": "classify_driver_details",
                "driver_details_decision": result.decision,
                "user_input": reply_text,
                "output": parsed,
                "prompt_step_key": DRIVER_ASSIGNMENT_DRIVER_DETAILS,
                "tenant_prompt_ref": prompt_metadata.tenant_prompt_ref,
                "prompt_source": prompt_metadata.source,
                "prompt_commit_hash": prompt_metadata.commit_hash,
            }
            activity_log_id = self._activity.record_action(
                ActivityLogWrite(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=workflow_lifecycle_id,
                    workflow_run_id=workflow_run_id,
                    description=format_driver_details_llm_action(
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
        latest_reply: str,
        reply_text: str,
        thread_message_count: int,
        reason: str,
    ) -> DriverDetailsClassificationResult:
        return DriverDetailsClassificationResult(
            decision=DO_NOTHING,
            reason=reason,
            confidence=0.0,
            normalized_reply=latest_reply,
            thread_llm_input=reply_text,
            thread_message_count=thread_message_count,
            llm_raw={
                "decision": DO_NOTHING,
                "confidence": 0.0,
                "reason": reason,
                "driver": {"name": None, "phone": None, "email": None},
            },
        )
