"""Tests for PromptService rendering (POD attachment-classifier — T3RA tenant)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.prompt_step_keys import POD_ATTACHMENT_CLASSIFIER, resolve_prompt_ref
from app.integrations.langsmith import MissingTenantPromptRefError
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.prompt_service import PromptService, resolve_pod_attachment_classifier_prompts
from tests.fixtures.t3ra_tenant_settings import T3RA_PROMPTS
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def test_render_step_loads_from_hub_when_ref_configured() -> None:
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
    rendered, metadata = prompt_service.render_step(
        {"prompts": T3RA_PROMPTS},
        POD_ATTACHMENT_CLASSIFIER,
        {},
    )
    assert rendered.system == "hub-sys"
    assert metadata.source == "hub"
    client.load_and_render.assert_called_once()


def test_render_step_missing_ref_raises() -> None:
    prompt_service = PromptService(prompt_client=MagicMock())
    with pytest.raises(MissingTenantPromptRefError):
        prompt_service.render_step({}, POD_ATTACHMENT_CLASSIFIER, {})


def test_t3ra_fixture_has_pod_prompt_refs() -> None:
    prompts = load_tenant_settings_dev("t3ra").get("prompts") or {}
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
