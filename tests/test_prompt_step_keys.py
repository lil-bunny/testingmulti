"""Tests for tenant prompt step key resolution."""

from __future__ import annotations

from app.domain.prompt_step_keys import (
    DRIVER_ASSIGNMENT_DRIVER_DETAILS,
    LOAD_TENDERING_CARRIER_ACK,
    POD_ATTACHMENT_CLASSIFIER,
    POD_PDF_EXTRACTION,
    resolve_prompt_ref,
)


def test_resolve_prompt_ref_nested_gelita() -> None:
    prompts = {
        "load_tendering": {
            "carrier_ack": "carrier-ack-classify:staging",
        }
    }
    assert resolve_prompt_ref(prompts, LOAD_TENDERING_CARRIER_ACK) == (
        "carrier-ack-classify:staging"
    )


def test_resolve_prompt_ref_nested_t3ra() -> None:
    prompts = {
        "pod_lifecycle": {
            "pdf_extraction": "pod-pdf-extraction:staging",
            "attachment_classifier": "pod-attachment-classifier:staging",
        },
        "driver_assignment": {
            "driver_details": "driver-details-extract:staging",
        },
    }
    assert resolve_prompt_ref(prompts, POD_PDF_EXTRACTION) == "pod-pdf-extraction:staging"
    assert (
        resolve_prompt_ref(prompts, POD_ATTACHMENT_CLASSIFIER)
        == "pod-attachment-classifier:staging"
    )
    assert (
        resolve_prompt_ref(prompts, DRIVER_ASSIGNMENT_DRIVER_DETAILS)
        == "driver-details-extract:staging"
    )


def test_resolve_prompt_ref_ignores_flat_keys() -> None:
    prompts = {
        LOAD_TENDERING_CARRIER_ACK: "carrier-ack-classify:staging",
    }
    assert resolve_prompt_ref(prompts, LOAD_TENDERING_CARRIER_ACK) == ""


def test_resolve_prompt_ref_missing_path_returns_empty() -> None:
    assert resolve_prompt_ref({}, LOAD_TENDERING_CARRIER_ACK) == ""
    assert resolve_prompt_ref({"load_tendering": {}}, LOAD_TENDERING_CARRIER_ACK) == ""
