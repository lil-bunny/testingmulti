"""LLM scheduling optimization wrapper (tools layer only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.appointment_scheduling.models import LlmSchedulingDecision
from app.integrations.langsmith.types import PromptTraceMetadata
from app.tools.appointment_scheduling.scheduling_fallback import fallback_scheduling_decision
from app.tools.appointment_scheduling.weekend_shifted import is_weekend_shifted_truthy
from app.tools.llm_client import LLMClientError, chat_json


def _weekday_from_date(date_mm_dd_yyyy: str) -> str:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_mm_dd_yyyy.strip(), fmt).strftime("%A").upper()
        except ValueError:
            continue
    return "DAY"


def _fallback_decision(location_input: dict[str, Any]) -> LlmSchedulingDecision:
    return fallback_scheduling_decision(
        pickup_mm_dd_yyyy=str(location_input.get("startDateInput") or ""),
        miles=location_input.get("miles") or 0,
        dropoff_state=str(location_input.get("dropoff_state") or ""),
    )


def run_scheduling_optimization(
    *,
    system_prompt: str,
    user_prompt: str,
    location_input: dict[str, Any],
    prompt_trace: PromptTraceMetadata | None = None,
) -> LlmSchedulingDecision:
    try:
        raw = chat_json(
            system_prompt,
            user_prompt,
            temperature=0.2,
            prompt_trace=prompt_trace,
        )
    except LLMClientError:
        return _fallback_decision(location_input)

    if not isinstance(raw, dict):
        raw = {}
    delivery_date = str(raw.get("calculated_delivery_date") or "")
    weekday = str(raw.get("calculated_delivery_weekday") or "")
    if delivery_date and not weekday:
        weekday = _weekday_from_date(delivery_date)
    return LlmSchedulingDecision(
        calculated_delivery_date=delivery_date,
        calculated_delivery_weekday=weekday,
        selected_pickup_date=raw.get("selected_pickup_date"),
        selected_pickup_time=raw.get("selected_pickup_time"),
        pcs_pickup_date=raw.get("pcs_pickup_date"),
        transit_days=raw.get("transit_days"),
        weekend_shifted=is_weekend_shifted_truthy(raw.get("weekend_shifted")),
    )
