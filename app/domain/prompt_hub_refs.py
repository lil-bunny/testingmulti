"""LangSmith Hub prompt names and ref formatting (not tenant step keys)."""

from __future__ import annotations

CARRIER_ACK_CLASSIFY_PROMPT = "carrier-ack-classify"
DRIVER_DETAILS_EXTRACT_PROMPT = "driver-details-extract"
POD_PAGE_EXTRACTION_PROMPT = "pod-page-extraction"
POD_ATTACHMENT_CLASSIFIER_PROMPT = "pod-attachment-classifier"
RATECON_PAGE_EXTRACTION_PROMPT = "ratecon-page-extraction"
POD_VS_RATECON_SUMMARY_PROMPT = "pod-vs-ratecon-summary"
POD_VS_RATECON_SEMANTIC_MATCH_PROMPT = "pod-vs-ratecon-semantic-match"
APPOINTMENT_SCHEDULING_CUSTOMER_REPLY_PROMPT = "appt-reply"
APPOINTMENT_SCHEDULING_OPTIMIZATION_PROMPT = "appt-scheduling-optimization"


def hub_prompt_id(prompt_name: str, *, owner: str | None = None) -> str:
    """
    Build a Hub identifier LangSmith accepts.

    With no owner, creates a private prompt in the API key's workspace.
    With owner, uses ``owner/prompt-name`` (owner must match that workspace).
    """
    name = prompt_name.strip()
    workspace = (owner or "").strip()
    if workspace:
        return f"{workspace}/{name}"
    return name


def hub_prompt_ref(prompt_name: str, tag: str, *, owner: str | None = None) -> str:
    """Hub pull ref including tag, e.g. ``carrier-ack-classify:production``."""
    return f"{hub_prompt_id(prompt_name, owner=owner)}:{tag.strip()}"
