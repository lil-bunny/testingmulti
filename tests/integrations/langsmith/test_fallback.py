"""Tests for git fallback prompt manifests."""

from __future__ import annotations

from app.domain.prompt_step_keys import (
    DRIVER_ASSIGNMENT_DRIVER_DETAILS,
    LOAD_TENDERING_CARRIER_ACK,
    POD_ATTACHMENT_CLASSIFIER,
    POD_PDF_EXTRACTION,
    resolve_prompt_ref,
)
from app.integrations.langsmith.fallback import (
    hub_id_from_tenant_prompt_ref,
    load_fallback_prompt,
)
from app.integrations.langsmith.render import render_system_user

CARRIER_ACK_HUB_ID = "carrier-ack-classify"
CARRIER_ACK_REF = f"{CARRIER_ACK_HUB_ID}:production"
DRIVER_DETAILS_HUB_ID = "driver-details-extract"
DRIVER_DETAILS_REF = f"{DRIVER_DETAILS_HUB_ID}:staging"


def test_hub_id_strips_tag() -> None:
    assert hub_id_from_tenant_prompt_ref(CARRIER_ACK_REF) == CARRIER_ACK_HUB_ID


def test_load_carrier_ack_fallback_renders_thread_text() -> None:
    template = load_fallback_prompt(CARRIER_ACK_HUB_ID)
    rendered = render_system_user(
        template,
        {"thread_text": "email 1\nWe accept the load."},
    )
    assert "load-tender email conversation" in rendered.system.lower()
    assert rendered.user == "email 1\nWe accept the load."


def test_load_driver_details_fallback_renders_thread_text() -> None:
    template = load_fallback_prompt(DRIVER_DETAILS_HUB_ID)
    rendered = render_system_user(
        template,
        {"thread_text": "email 1\nDriver John 555-0100"},
    )
    assert "driver contact details" in rendered.system.lower()
    assert "has_details" in rendered.system
    assert rendered.user == "email 1\nDriver John 555-0100"


def test_gelita_fixture_prompt_ref_matches_fallback_hub_id() -> None:
    from tests.fixtures.tenant_settings import load_tenant_settings_dev

    from app.domain.prompt_step_keys import resolve_prompt_ref

    prompts = load_tenant_settings_dev("gelita").get("prompts") or {}
    ref = resolve_prompt_ref(prompts, LOAD_TENDERING_CARRIER_ACK)
    assert hub_id_from_tenant_prompt_ref(ref) == CARRIER_ACK_HUB_ID
    assert "load_tendering" in prompts
    assert "pod_lifecycle" not in prompts


def test_t3ra_fixture_prompt_refs_match_fallback_hub_ids() -> None:
    from tests.fixtures.tenant_settings import load_tenant_settings_dev

    prompts = load_tenant_settings_dev("t3ra").get("prompts") or {}
    assert hub_id_from_tenant_prompt_ref(
        resolve_prompt_ref(prompts, POD_PDF_EXTRACTION)
    ) == "pod-pdf-extraction"
    assert hub_id_from_tenant_prompt_ref(
        resolve_prompt_ref(prompts, DRIVER_ASSIGNMENT_DRIVER_DETAILS)
    ) == (DRIVER_DETAILS_HUB_ID)
    assert hub_id_from_tenant_prompt_ref(
        resolve_prompt_ref(prompts, POD_ATTACHMENT_CLASSIFIER)
    ) == "pod-attachment-classifier"


def test_load_pod_pdf_extraction_fallback_renders_schema() -> None:
    template = load_fallback_prompt("pod-pdf-extraction")
    rendered = render_system_user(template, {})
    assert "Proof of Delivery" in rendered.system
    assert "document_summary" in rendered.system
    assert "reconciled" in rendered.system
    assert "Analyze the attached complete POD PDF" in rendered.user


def test_load_pod_attachment_classifier_fallback_renders_prompts() -> None:
    template = load_fallback_prompt("pod-attachment-classifier")
    rendered = render_system_user(template, {})
    assert "logistics document classifier" in rendered.user.lower()
    assert "is_valid_document" in rendered.user
    assert "classify logistics document validity" in rendered.system.lower()


def test_load_appt_reply_fallback_renders_thread_text() -> None:
    template = load_fallback_prompt("appt-reply")
    thread = "email 1 [outbound]\n04/03/2026\nemail 2 [inbound]\n5PM"
    rendered = render_system_user(template, {"thread_text": thread})
    assert "accepted" in rendered.system
    assert thread in rendered.user
    assert "Sent Items and Inbox" in rendered.user
