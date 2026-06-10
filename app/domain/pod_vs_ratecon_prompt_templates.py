"""Canonical POD vs RateCon validation summary prompt (Hub seed + inline fallback)."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

POD_VS_RATECON_SUMMARY_SYSTEM = (
    "You are a logistics validation expert. Provide concise, accurate summaries of "
    "POD vs RateCon validation results for freight operations. Always respond with valid JSON."
)

POD_VS_RATECON_SUMMARY_USER = """Analyze this POD vs RateCon cross-validation result and provide a concise 2-line summary with confidence score.

VALIDATION RESULTS:
{cross_validation_json}

POD ANALYSIS DATA:
- Signature Present: {signature_present}
- Stamp Present: {stamp_present}
- Delivery Confirmed: {delivery_confirmed}
- Delivery Confirmation Reasoning: {delivery_confirmation_reasoning}

INSTRUCTIONS:
1. Provide exactly 2 lines (no more, no less):
   - Line 1: Field matches/discrepancies summary
   - Line 2: Delivery status and key business insights

2. Calculate confidence score (0.0 to 1.0) using simple 50/50 weighting:
   - 50% weight: Signature/Stamp/Delivery confirmations (higher points for present/confirmed)
   - 50% weight: Field validation results (higher points for PASS status)

   Simple scoring logic:
   - Signature present: +0.15 points
   - Stamp present: +0.15 points
   - Delivery confirmed: +0.20 points
   - Each field validation PASS: +0.50 points divided by total fields
   - Start from base 0.1, cap at 1.0

3. Do NOT mention "PASS", "FAIL", or "Line 1/Line 2" in summary. Be direct and business-focused.

RESPONSE FORMAT (JSON only):
{{
  "summary": "Field validation summary line.\\nDelivery confirmation and business insights line.",
  "confidence_score": 0.85
}}

Be extremely concise."""


def summary_prompt_variables(
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
) -> dict[str, str]:
    return {
        "cross_validation_json": json.dumps(cross_validation, indent=2),
        "signature_present": str(pod_analysis.get("signature_present", False)),
        "stamp_present": str(pod_analysis.get("stamp_present", False)),
        "delivery_confirmed": str(pod_analysis.get("delivery_confirmed", False)),
        "delivery_confirmation_reasoning": str(
            pod_analysis.get("delivery_confirmation_reasoning") or ""
        ),
    }


def render_inline_pod_vs_ratecon_summary_prompts(
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
) -> tuple[str, str]:
    variables = summary_prompt_variables(cross_validation, pod_analysis)
    user = POD_VS_RATECON_SUMMARY_USER.format(**variables)
    return POD_VS_RATECON_SUMMARY_SYSTEM, user


def build_pod_vs_ratecon_summary_seed_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", POD_VS_RATECON_SUMMARY_SYSTEM),
            ("human", POD_VS_RATECON_SUMMARY_USER),
        ]
    )
