"""Tests for tenant prompt ref resolution (flat and nested)."""

from __future__ import annotations

from app.domain.prompt_step_keys import (
    DRIVER_ASSIGNMENT_DRIVER_DETAILS,
    LOAD_TENDERING_CARRIER_ACK,
    POD_PAGE_EXTRACTION,
    POD_VS_RATECON_SEMANTIC_MATCH,
    POD_VS_RATECON_SUMMARY,
    RATECON_PAGE_EXTRACTION,
)
from app.domain.tenant_settings.prompt_refs import tenant_prompt_ref


def test_flat_prompt_ref_resolves() -> None:
    prompts = {LOAD_TENDERING_CARRIER_ACK: "carrier-ack-classify:production"}
    assert tenant_prompt_ref(prompts, LOAD_TENDERING_CARRIER_ACK) == (
        "carrier-ack-classify:production"
    )


def test_nested_t3ra_prompt_refs_resolve() -> None:
    prompts = {
        "pod_lifecycle": {
            "page_extraction": "pod-page-extraction:staging",
            "vs_ratecon_summary": "pod-vs-ratecon-summary:staging",
            "vs_ratecon_semantic_match": "pod-vs-ratecon-semantic-match:staging",
        },
        "ratecon": {"page_extraction": "ratecon-page-extraction:staging"},
        "driver_assignment": {"driver_details": "driver-details-extract:staging"},
    }
    assert tenant_prompt_ref(prompts, POD_PAGE_EXTRACTION) == "pod-page-extraction:staging"
    assert tenant_prompt_ref(prompts, RATECON_PAGE_EXTRACTION) == "ratecon-page-extraction:staging"
    assert tenant_prompt_ref(prompts, POD_VS_RATECON_SUMMARY) == "pod-vs-ratecon-summary:staging"
    assert (
        tenant_prompt_ref(prompts, POD_VS_RATECON_SEMANTIC_MATCH)
        == "pod-vs-ratecon-semantic-match:staging"
    )
    assert (
        tenant_prompt_ref(prompts, DRIVER_ASSIGNMENT_DRIVER_DETAILS)
        == "driver-details-extract:staging"
    )


def test_flat_takes_precedence_over_nested() -> None:
    prompts = {
        POD_PAGE_EXTRACTION: "legacy-flat-ref:staging",
        "pod_lifecycle": {"page_extraction": "pod-page-extraction:staging"},
    }
    assert tenant_prompt_ref(prompts, POD_PAGE_EXTRACTION) == "legacy-flat-ref:staging"


def test_missing_ref_returns_empty() -> None:
    assert tenant_prompt_ref({}, POD_PAGE_EXTRACTION) == ""
    assert tenant_prompt_ref({"pod_lifecycle": {}}, POD_PAGE_EXTRACTION) == ""
