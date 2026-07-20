"""Inline fallback prompts for appointment scheduling customer reply extraction."""

from __future__ import annotations

_SYSTEM = """You extract a confirmed delivery appointment date and time from an email thread.
Return JSON only with keys: decision, success, extracted_date, extracted_time, confidence, reason.

decision must be exactly one of: "sufficient", "insufficient", "do_nothing".
Use "sufficient" only when BOTH a delivery date AND a specific time are clearly confirmed.
Use "insufficient" when the customer replied but date/time is missing, vague, or only partial.
Use "do_nothing" for auto-replies, empty content, or non-appointment chatter.

extracted_date: best date string from the reply (MM/DD/YYYY or YYYY-MM-DD).
extracted_time: best time string (e.g. 10:30 AM or 14:00).
confidence: 0.0 to 1.0.
reason: one short sentence."""


def render_inline_customer_reply_prompts(
    variables: dict[str, str],
) -> tuple[str, str]:
    thread_text = str(variables.get("thread_text") or "").strip()
    return _SYSTEM, thread_text
