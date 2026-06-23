"""Stable tenant-settings keys for LangSmith-managed LLM steps (not Hub ids)."""

from __future__ import annotations

from typing import Any

LOAD_TENDERING_CARRIER_ACK = "load_tendering.carrier_ack"
DRIVER_ASSIGNMENT_DRIVER_DETAILS = "driver_assignment.driver_details"
POD_PAGE_EXTRACTION = "pod_lifecycle.page_extraction"
RATECON_PAGE_EXTRACTION = "ratecon.page_extraction"
POD_VS_RATECON_SUMMARY = "pod_lifecycle.vs_ratecon_summary"
POD_VS_RATECON_SEMANTIC_MATCH = "pod_lifecycle.vs_ratecon_semantic_match"


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
