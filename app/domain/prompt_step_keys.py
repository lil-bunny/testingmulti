"""
Stable tenant-settings keys for LangSmith-managed LLM steps (not Hub ids),
plus LangSmith Hub prompt names and ref formatting.
"""

from __future__ import annotations

from typing import Any

# Tenant-settings step keys (``tenants.settings.prompts`` dot paths).
LOAD_TENDERING_CARRIER_ACK = "load_tendering.carrier_ack"
DRIVER_ASSIGNMENT_DRIVER_DETAILS = "driver_assignment.driver_details"
POD_PAGE_EXTRACTION = "pod_lifecycle.page_extraction"
POD_PDF_EXTRACTION = "pod_lifecycle.pdf_extraction"
POD_ATTACHMENT_CLASSIFIER = "pod_lifecycle.attachment_classifier"
RATECON_PAGE_EXTRACTION = "ratecon.page_extraction"
POD_VS_RATECON_SUMMARY = "pod_lifecycle.vs_ratecon_summary"
POD_VS_RATECON_SEMANTIC_MATCH = "pod_lifecycle.vs_ratecon_semantic_match"
APPOINTMENT_SCHEDULING_OPTIMIZATION = "appointment_scheduling.scheduling_optimization"
APPOINTMENT_SCHEDULING_CUSTOMER_REPLY = "appointment_scheduling.customer_reply"

# LangSmith Hub prompt names (not tenant step keys).
CARRIER_ACK_CLASSIFY_PROMPT = "carrier-ack-classify"
DRIVER_DETAILS_EXTRACT_PROMPT = "driver-details-extract"
POD_PAGE_EXTRACTION_PROMPT = "pod-page-extraction"
POD_PDF_EXTRACTION_PROMPT = "pod-pdf-extraction"
POD_ATTACHMENT_CLASSIFIER_PROMPT = "pod-attachment-classifier"
RATECON_PAGE_EXTRACTION_PROMPT = "ratecon-page-extraction"
POD_VS_RATECON_SUMMARY_PROMPT = "pod-vs-ratecon-summary"
POD_VS_RATECON_SEMANTIC_MATCH_PROMPT = "pod-vs-ratecon-semantic-match"


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


def resolve_prompt_ref(prompts: Any, prompt_step_key: str) -> str:
    """
    Resolve a LangSmith prompt ref from nested tenant ``prompts``.

    Walks dot-separated path segments (e.g. ``load_tendering.carrier_ack`` →
    ``prompts["load_tendering"]["carrier_ack"]``).
    """
    if not isinstance(prompts, dict):
        return ""
    node: Any = prompts
    for part in prompt_step_key.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part)
    if node is None or isinstance(node, dict):
        return ""
    return str(node).strip()
