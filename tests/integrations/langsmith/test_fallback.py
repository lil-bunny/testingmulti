"""Tests for git fallback prompt manifests."""

from __future__ import annotations

from app.domain.prompt_step_keys import LOAD_TENDERING_CARRIER_ACK
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
    assert "classify carrier email" in rendered.system.lower()
    assert rendered.user == "email 1\nWe accept the load."


def test_gelita_fixture_prompt_ref_matches_fallback_hub_id() -> None:
    from tests.fixtures.tenant_settings import load_tenant_settings_dev

    prompts = load_tenant_settings_dev("gelita").get("prompts") or {}
    ref = prompts[LOAD_TENDERING_CARRIER_ACK]
    assert hub_id_from_tenant_prompt_ref(ref) == CARRIER_ACK_HUB_ID
