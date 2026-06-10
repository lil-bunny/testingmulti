"""Tests for vision prompt resolution (POD and ratecon — T3RA tenant)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.prompt_step_keys import (
    POD_PAGE_EXTRACTION,
    POD_VS_RATECON_SEMANTIC_MATCH,
    POD_VS_RATECON_SUMMARY,
    RATECON_PAGE_EXTRACTION,
)
from app.integrations.langsmith import PromptUnavailableError
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.prompt_service import (
    PromptService,
    resolve_pod_vision_prompts,
    resolve_pod_vs_ratecon_semantic_match_prompts,
    resolve_pod_vs_ratecon_summary_prompts,
    resolve_ratecon_vision_prompts,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def test_render_vision_step_uses_inline_when_no_tenant_ref() -> None:
    prompt_service = PromptService(prompt_client=MagicMock())
    rendered, metadata = prompt_service.render_vision_step(
        {},
        POD_PAGE_EXTRACTION,
        {"broker_name": "Acme", "broker_context": "ctx"},
        inline_fallback=("inline-sys", "inline-usr"),
    )
    assert rendered.system == "inline-sys"
    assert rendered.user == "inline-usr"
    assert metadata.source == "fallback"
    assert metadata.tenant_prompt_ref == "inline"


def test_render_vision_step_loads_from_hub_when_ref_configured() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="hub-sys", user="hub-usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="pod-page-extraction:staging",
            commit_hash="abc",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = prompt_service.render_vision_step(
        {
            "prompts": {
                POD_PAGE_EXTRACTION: "pod-page-extraction:staging",
            }
        },
        POD_PAGE_EXTRACTION,
        {"broker_name": "", "broker_context": ""},
        inline_fallback=("inline-sys", "inline-usr"),
    )
    assert rendered.system == "hub-sys"
    assert metadata.source == "hub"
    client.load_and_render.assert_called_once()


def test_render_vision_step_inline_when_hub_unavailable() -> None:
    client = MagicMock()
    client.load_and_render.side_effect = PromptUnavailableError("down")
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = prompt_service.render_vision_step(
        {
            "prompts": {
                RATECON_PAGE_EXTRACTION: "ratecon-page-extraction:staging",
            }
        },
        RATECON_PAGE_EXTRACTION,
        {},
        inline_fallback=("inline-sys", "inline-usr"),
    )
    assert rendered.system == "inline-sys"
    assert metadata.tenant_prompt_ref == "ratecon-page-extraction:staging"


def test_resolve_pod_vision_prompts_includes_broker_variables() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user=" "),
        PromptLoadMetadata(source="hub", tenant_prompt_ref="pod-page-extraction:staging"),
    )
    prompt_service = PromptService(prompt_client=client)
    resolve_pod_vision_prompts(
        {"prompts": {POD_PAGE_EXTRACTION: "pod-page-extraction:staging"}},
        "T3RA Logistics",
        prompt_service=prompt_service,
    )
    _ref, variables = client.load_and_render.call_args[0]
    assert variables["broker_name"] == "T3RA Logistics"
    assert "T3RA Logistics" in variables["broker_context"]


def test_t3ra_fixture_has_pod_and_ratecon_prompt_refs() -> None:
    prompts = load_tenant_settings_dev("t3ra").get("prompts") or {}
    assert prompts[POD_PAGE_EXTRACTION] == "pod-page-extraction:staging"
    assert prompts[RATECON_PAGE_EXTRACTION] == "ratecon-page-extraction:staging"
    assert prompts[POD_VS_RATECON_SUMMARY] == "pod-vs-ratecon-summary:staging"
    assert prompts[POD_VS_RATECON_SEMANTIC_MATCH] == "pod-vs-ratecon-semantic-match:staging"


def test_resolve_pod_vs_ratecon_summary_includes_validation_json() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user="usr"),
        PromptLoadMetadata(source="hub", tenant_prompt_ref="pod-vs-ratecon-summary:staging"),
    )
    prompt_service = PromptService(prompt_client=client)
    cross = {"overall_status": "PASS", "field_validations": []}
    pod = {
        "signature_present": True,
        "stamp_present": False,
        "delivery_confirmed": True,
        "delivery_confirmation_reasoning": "signed",
    }
    resolve_pod_vs_ratecon_summary_prompts(
        {"prompts": {POD_VS_RATECON_SUMMARY: "pod-vs-ratecon-summary:staging"}},
        cross,
        pod,
        prompt_service=prompt_service,
    )
    _ref, variables = client.load_and_render.call_args[0]
    assert "overall_status" in variables["cross_validation_json"]
    assert variables["signature_present"] == "True"
    assert variables["delivery_confirmation_reasoning"] == "signed"


def test_resolve_pod_vs_ratecon_semantic_match_includes_field_values() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user="usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="pod-vs-ratecon-semantic-match:staging",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    resolve_pod_vs_ratecon_semantic_match_prompts(
        {
            "prompts": {
                POD_VS_RATECON_SEMANTIC_MATCH: "pod-vs-ratecon-semantic-match:staging",
            }
        },
        "pickup_address",
        "RIPON, CA 95366",
        "2151 River Plaza Dr, Sacramento, CA, 95833",
        prompt_service=prompt_service,
    )
    _ref, variables = client.load_and_render.call_args[0]
    assert variables["field_type"] == "pickup_address"
    assert variables["pod_value"] == "RIPON, CA 95366"
    assert variables["ratecon_value"] == "2151 River Plaza Dr, Sacramento, CA, 95833"
