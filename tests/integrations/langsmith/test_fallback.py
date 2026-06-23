"""Tests for git fallback prompt manifests."""

from __future__ import annotations

from app.domain.prompt_step_keys import (
    LOAD_TENDERING_CARRIER_ACK,
    POD_PAGE_EXTRACTION,
    POD_VS_RATECON_SEMANTIC_MATCH,
    POD_VS_RATECON_SUMMARY,
    RATECON_PAGE_EXTRACTION,
    resolve_prompt_ref,
)
from app.integrations.langsmith.fallback import (
    hub_id_from_tenant_prompt_ref,
    load_fallback_prompt,
)
from app.integrations.langsmith.render import render_system_user

CARRIER_ACK_HUB_ID = "carrier-ack-classify"
CARRIER_ACK_REF = f"{CARRIER_ACK_HUB_ID}:production"


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
        resolve_prompt_ref(prompts, POD_PAGE_EXTRACTION)
    ) == "pod-page-extraction"
    assert hub_id_from_tenant_prompt_ref(
        resolve_prompt_ref(prompts, RATECON_PAGE_EXTRACTION)
    ) == "ratecon-page-extraction"
    assert hub_id_from_tenant_prompt_ref(
        resolve_prompt_ref(prompts, POD_VS_RATECON_SUMMARY)
    ) == "pod-vs-ratecon-summary"
    assert (
        hub_id_from_tenant_prompt_ref(
            resolve_prompt_ref(prompts, POD_VS_RATECON_SEMANTIC_MATCH)
        )
        == "pod-vs-ratecon-semantic-match"
    )


def test_load_pod_vs_ratecon_summary_fallback_renders_variables() -> None:
    template = load_fallback_prompt("pod-vs-ratecon-summary")
    rendered = render_system_user(
        template,
        {
            "cross_validation_json": '{"overall_status": "PASS"}',
            "signature_present": "True",
            "stamp_present": "False",
            "delivery_confirmed": "True",
            "delivery_confirmation_reasoning": "signed",
        },
    )
    assert "logistics validation expert" in rendered.system.lower()
    assert "overall_status" in rendered.user
    assert "signed" in rendered.user


def test_load_pod_vs_ratecon_semantic_match_fallback_renders_variables() -> None:
    template = load_fallback_prompt("pod-vs-ratecon-semantic-match")
    rendered = render_system_user(
        template,
        {
            "field_type": "pickup_address",
            "pod_value": "RIPON, CA 95366",
            "ratecon_value": "2151 River Plaza Dr, Sacramento, CA, 95833",
        },
    )
    assert "logistics data auditor" in rendered.system.lower()
    assert "pickup_address" in rendered.user
    assert "RIPON" in rendered.user
    assert "Sacramento" in rendered.user


def test_load_pod_page_fallback_renders_broker_context() -> None:
    template = load_fallback_prompt("pod-page-extraction")
    rendered = render_system_user(
        template,
        {"broker_name": "T3RA", "broker_context": "\n\nbroker rule"},
    )
    assert "Proof of Delivery" in rendered.system
    assert "broker rule" in rendered.system


def test_load_ratecon_page_fallback_renders_user_mission() -> None:
    template = load_fallback_prompt("ratecon-page-extraction")
    rendered = render_system_user(template, {})
    assert "document intelligence" in rendered.system.lower()
    assert "MISSION" in rendered.user
