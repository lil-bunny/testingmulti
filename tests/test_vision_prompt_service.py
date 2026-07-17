"""Tests for vision prompt resolution (POD and ratecon — T3RA tenant)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.prompt_step_keys import (
    POD_ATTACHMENT_CLASSIFIER,
    POD_PAGE_EXTRACTION,
    POD_VS_RATECON_SEMANTIC_MATCH,
    POD_VS_RATECON_SUMMARY,
    RATECON_PAGE_EXTRACTION,
    resolve_prompt_ref,
)
from app.integrations.langsmith import MissingTenantPromptRefError
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.prompt_service import (
    PromptService,
    resolve_pod_attachment_classifier_prompts,
    resolve_pod_vision_prompts,
    resolve_pod_vs_ratecon_semantic_match_prompts,
    resolve_pod_vs_ratecon_summary_prompts,
)
from tests.fixtures.t3ra_tenant_settings import T3RA_PROMPTS
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def test_render_step_loads_from_hub_when_ref_configured() -> None:
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
    rendered, metadata = prompt_service.render_step(
        {"prompts": T3RA_PROMPTS},
        POD_PAGE_EXTRACTION,
        {"broker_name": "", "broker_context": ""},
    )
    assert rendered.system == "hub-sys"
    assert metadata.source == "hub"
    client.load_and_render.assert_called_once()


def test_render_step_missing_ref_raises() -> None:
    prompt_service = PromptService(prompt_client=MagicMock())
    with pytest.raises(MissingTenantPromptRefError):
        prompt_service.render_step(
            {},
            POD_PAGE_EXTRACTION,
            {"broker_name": "Acme", "broker_context": "ctx"},
        )


def test_resolve_pod_vision_prompts_includes_broker_variables() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user=" "),
        PromptLoadMetadata(source="hub", tenant_prompt_ref="pod-page-extraction:staging"),
    )
    prompt_service = PromptService(prompt_client=client)
    resolve_pod_vision_prompts(
        {"prompts": T3RA_PROMPTS},
        "T3RA Logistics",
        prompt_service=prompt_service,
    )
    _ref, variables = client.load_and_render.call_args[0]
    assert variables["broker_name"] == "T3RA Logistics"
    assert "T3RA Logistics" in variables["broker_context"]


def test_t3ra_fixture_has_pod_and_ratecon_prompt_refs() -> None:
    prompts = load_tenant_settings_dev("t3ra").get("prompts") or {}
    assert resolve_prompt_ref(prompts, POD_PAGE_EXTRACTION) == "pod-page-extraction:staging"
    assert resolve_prompt_ref(prompts, RATECON_PAGE_EXTRACTION) == "ratecon-page-extraction:staging"
    assert resolve_prompt_ref(prompts, POD_VS_RATECON_SUMMARY) == "pod-vs-ratecon-summary:staging"
    assert (
        resolve_prompt_ref(prompts, POD_VS_RATECON_SEMANTIC_MATCH)
        == "pod-vs-ratecon-semantic-match:staging"
    )
    assert (
        resolve_prompt_ref(prompts, POD_ATTACHMENT_CLASSIFIER)
        == "pod-attachment-classifier:staging"
    )


def test_resolve_pod_attachment_classifier_prompts_requires_ref() -> None:
    with pytest.raises(MissingTenantPromptRefError):
        resolve_pod_attachment_classifier_prompts({})


def test_resolve_pod_attachment_classifier_prompts_loads_from_hub() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="hub-sys", user="hub-usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="pod-attachment-classifier:staging",
            commit_hash="abc",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = resolve_pod_attachment_classifier_prompts(
        {"prompts": T3RA_PROMPTS},
        prompt_service=prompt_service,
    )
    assert rendered.system == "hub-sys"
    assert rendered.user == "hub-usr"
    assert metadata.source == "hub"
    client.load_and_render.assert_called_once_with(
        "pod-attachment-classifier:staging",
        {},
    )


def test_resolve_ratecon_vision_prompts_loads_from_hub() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="hub-sys", user="hub-usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="ratecon-page-extraction:staging",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = resolve_ratecon_vision_prompts(
        {"prompts": T3RA_PROMPTS},
        prompt_service=prompt_service,
    )
    assert rendered.system == "hub-sys"
    assert metadata.source == "hub"


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
        {"prompts": T3RA_PROMPTS},
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
        {"prompts": T3RA_PROMPTS},
        "pickup_address",
        "RIPON, CA 95366",
        "2151 River Plaza Dr, Sacramento, CA, 95833",
        prompt_service=prompt_service,
    )
    _ref, variables = client.load_and_render.call_args[0]
    assert variables["field_type"] == "pickup_address"
    assert variables["pod_value"] == "RIPON, CA 95366"
    assert variables["ratecon_value"] == "2151 River Plaza Dr, Sacramento, CA, 95833"
