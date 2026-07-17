"""Resolve tenant prompt refs and render LangSmith-managed LLM steps.

Prompts load from Hub, then ``prompts/fallbacks/*.json`` — never from inline
Python template strings.
"""

from __future__ import annotations

from typing import Any

from app.domain.prompt_step_keys import resolve_prompt_ref
from app.integrations.langsmith import (
    LangSmithPromptClient,
    MissingTenantPromptRefError,
    PromptLoadMetadata,
    RenderedPrompt,
)


class PromptService:
    def __init__(self, *, prompt_client: LangSmithPromptClient | None = None) -> None:
        self._prompt_client = prompt_client or LangSmithPromptClient()

    def render_step(
        self,
        tenant_settings: dict[str, Any],
        prompt_step_key: str,
        variables: dict[str, str],
    ) -> tuple[RenderedPrompt, PromptLoadMetadata]:
        """Resolve tenant prompt ref and render system/user with ``variables``.

        Raises ``MissingTenantPromptRefError`` when the step key is unset.
        Load order is Hub, then ``prompts/fallbacks/*.json``.
        """
        prompts = tenant_settings.get("prompts") or {}
        tenant_prompt_ref = resolve_prompt_ref(prompts, prompt_step_key)
        if not tenant_prompt_ref:
            raise MissingTenantPromptRefError(
                f"missing tenant prompt ref for step {prompt_step_key!r}"
            )
        return self._prompt_client.load_and_render(tenant_prompt_ref, variables)


def _tenant_settings_dict(
    tenant_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    return tenant_settings if isinstance(tenant_settings, dict) else {}


def resolve_pod_vision_prompts(
    tenant_settings: dict[str, Any] | None,
    broker_name: str | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render POD page-extraction prompts with ``broker_name`` / ``broker_context``."""
    from app.domain.prompt_step_keys import POD_PAGE_EXTRACTION
    from app.domain.vision_prompt_variables import pod_prompt_variables

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        POD_PAGE_EXTRACTION,
        pod_prompt_variables(broker_name),
    )


def resolve_pod_attachment_classifier_prompts(
    tenant_settings: dict[str, Any] | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render POD attachment-classifier prompts (no template variables)."""
    from app.domain.prompt_step_keys import POD_ATTACHMENT_CLASSIFIER

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        POD_ATTACHMENT_CLASSIFIER,
        {},
    )


def resolve_ratecon_vision_prompts(
    tenant_settings: dict[str, Any] | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render ratecon page-extraction prompts (no template variables)."""
    from app.domain.prompt_step_keys import RATECON_PAGE_EXTRACTION

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        RATECON_PAGE_EXTRACTION,
        {},
    )


def resolve_pod_vs_ratecon_summary_prompts(
    tenant_settings: dict[str, Any] | None,
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render POD-vs-RateCon summary prompt from validation + POD analysis fields."""
    from app.domain.pod_lifecycle.vs_ratecon_prompt_variables import (
        summary_prompt_variables,
    )
    from app.domain.prompt_step_keys import POD_VS_RATECON_SUMMARY

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        POD_VS_RATECON_SUMMARY,
        summary_prompt_variables(cross_validation, pod_analysis),
    )


def resolve_pod_vs_ratecon_semantic_match_prompts(
    tenant_settings: dict[str, Any] | None,
    field_type: str,
    pod_value: str,
    ratecon_value: str,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render one-field semantic-match prompt for POD vs RateCon comparison."""
    from app.domain.pod_lifecycle.vs_ratecon_prompt_variables import (
        semantic_match_prompt_variables,
    )
    from app.domain.prompt_step_keys import POD_VS_RATECON_SEMANTIC_MATCH

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        POD_VS_RATECON_SEMANTIC_MATCH,
        semantic_match_prompt_variables(field_type, pod_value, ratecon_value),
    )
