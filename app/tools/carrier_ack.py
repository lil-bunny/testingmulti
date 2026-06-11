"""Carrier acknowledgment reply parsing and LLM classification."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.integrations.langsmith.types import PromptTraceMetadata
from app.models.status import StatusSubType
from app.services.communications._mapper import normalize_email_body_for_llm
from app.tools.llm_client import LLMClientError, chat_json

logger = get_logger(__name__)

_CARRIER_ACK_DECISIONS = frozenset(
    {
        StatusSubType.ACCEPTED.value,
        StatusSubType.REJECTED.value,
        StatusSubType.DO_NOTHING.value,
    }
)


def normalize_carrier_reply_body(*, body: str | None = None) -> str:
    """Plain reply text for LLM (delegates to shared email body normalizer)."""
    return normalize_email_body_for_llm(body=body)


def _normalize_carrier_ack_decision(raw: dict[str, Any]) -> str:
    """Map LLM output to ``accepted`` | ``rejected`` | ``do_nothing``."""
    decision = str(raw.get("decision") or "").strip().lower()
    if decision in _CARRIER_ACK_DECISIONS:
        return decision
    if bool(raw.get("is_acknowledgment")):
        return StatusSubType.ACCEPTED.value
    return StatusSubType.DO_NOTHING.value


def classify_carrier_acknowledgment(
    reply_text: str,
    *,
    system_prompt: str,
    user_prompt: str | None = None,
    prompt_trace: PromptTraceMetadata | None = None,
) -> dict[str, Any]:
    """
    LLM gate for carrier ack replies.

    Returns ``decision`` (``accepted`` | ``rejected`` | ``do_nothing``), ``confidence``, ``reason``.
    """
    text = (reply_text or "").strip()
    user_content = (user_prompt if user_prompt is not None else reply_text) or ""
    user_content = user_content.strip()
    prompt = (system_prompt or "").strip()
    if not text:
        return {
            "decision": StatusSubType.DO_NOTHING.value,
            "confidence": 1.0,
            "reason": "empty reply body",
        }
    if not prompt:
        return {
            "decision": StatusSubType.DO_NOTHING.value,
            "confidence": 0.0,
            "reason": "missing_tenant_prompt_configuration",
        }

    try:
        raw = chat_json(
            prompt,
            user_content,
            temperature=0.1,
            prompt_trace=prompt_trace,
        )
    except LLMClientError as exc:
        logger.warning("carrier ack LLM failed: %s", exc)
        return {
            "decision": StatusSubType.DO_NOTHING.value,
            "confidence": 0.0,
            "reason": f"llm_error: {exc}",
        }

    decision = _normalize_carrier_ack_decision(raw)
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(raw.get("reason") or "").strip() or "no reason"

    return {
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
    }
