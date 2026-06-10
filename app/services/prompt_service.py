"""Resolve tenant prompt refs and render LangSmith-managed LLM steps."""

from __future__ import annotations

import logging
from typing import Any

from app.domain.vision_prompt_templates import (
    render_inline_pod_prompts,
    render_inline_ratecon_prompts,
)
from app.integrations.langsmith import (
    LangSmithPromptClient,
    MissingTenantPromptRefError,
    PromptLoadMetadata,
    PromptUnavailableError,
    RenderedPrompt,
)

logger = logging.getLogger(__name__)


class PromptService:
    def __init__(self, *, prompt_client: LangSmithPromptClient | None = None) -> None:
        self._prompt_client = prompt_client or LangSmithPromptClient()

    def render_step(
        self,
        tenant_settings: dict[str, Any],
        prompt_step_key: str,
        variables: dict[str, str],
    ) -> tuple[RenderedPrompt, PromptLoadMetadata]:
        prompts = tenant_settings.get("prompts") or {}
        if not isinstance(prompts, dict):
            prompts = {}
        tenant_prompt_ref = str(prompts.get(prompt_step_key) or "").strip()
        if not tenant_prompt_ref:
            raise MissingTenantPromptRefError(
                f"missing tenant prompt ref for step {prompt_step_key!r}"
            )
        return self._prompt_client.load_and_render(tenant_prompt_ref, variables)

    def render_vision_step(
        self,
        tenant_settings: dict[str, Any] | None,
        prompt_step_key: str,
        variables: dict[str, str],
        *,
        inline_fallback: tuple[str, str],
    ) -> tuple[RenderedPrompt, PromptLoadMetadata]:
        """
        Render a vision prompt from Hub (with JSON fallback) or inline template.

        When the tenant has no ``prompts`` ref for ``prompt_step_key``, uses
        ``inline_fallback`` so local/tests keep working without Hub configuration.
        """
        settings_dict = tenant_settings if isinstance(tenant_settings, dict) else {}
        prompts = settings_dict.get("prompts") or {}
        if not isinstance(prompts, dict):
            prompts = {}
        tenant_prompt_ref = str(prompts.get(prompt_step_key) or "").strip()
        if not tenant_prompt_ref:
            system, user = inline_fallback
            logger.debug(
                "vision prompt inline fallback step=%s (no tenant ref)",
                prompt_step_key,
            )
            return (
                RenderedPrompt(system=system, user=user),
                PromptLoadMetadata(
                    source="fallback",
                    tenant_prompt_ref="inline",
                    commit_hash=None,
                ),
            )
        try:
            return self.render_step(settings_dict, prompt_step_key, variables)
        except PromptUnavailableError as exc:
            logger.warning(
                "vision prompt hub unavailable step=%s ref=%s: %s; using inline fallback",
                prompt_step_key,
                tenant_prompt_ref,
                exc,
            )
            system, user = inline_fallback
            return (
                RenderedPrompt(system=system, user=user),
                PromptLoadMetadata(
                    source="fallback",
                    tenant_prompt_ref=tenant_prompt_ref,
                    commit_hash=None,
                ),
            )


def resolve_pod_vision_prompts(
    tenant_settings: dict[str, Any] | None,
    broker_name: str | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    service = prompt_service or PromptService()
    from app.domain.prompt_step_keys import POD_PAGE_EXTRACTION
    from app.domain.vision_prompt_templates import pod_prompt_variables

    return service.render_vision_step(
        tenant_settings,
        POD_PAGE_EXTRACTION,
        pod_prompt_variables(broker_name),
        inline_fallback=render_inline_pod_prompts(broker_name),
    )


def resolve_ratecon_vision_prompts(
    tenant_settings: dict[str, Any] | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    service = prompt_service or PromptService()
    from app.domain.prompt_step_keys import RATECON_PAGE_EXTRACTION

    return service.render_vision_step(
        tenant_settings,
        RATECON_PAGE_EXTRACTION,
        {},
        inline_fallback=render_inline_ratecon_prompts(),
    )


def resolve_pod_vs_ratecon_summary_prompts(
    tenant_settings: dict[str, Any] | None,
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    from app.domain.pod_vs_ratecon_prompt_templates import (
        render_inline_pod_vs_ratecon_summary_prompts,
        summary_prompt_variables,
    )
    from app.domain.prompt_step_keys import POD_VS_RATECON_SUMMARY

    service = prompt_service or PromptService()
    return service.render_vision_step(
        tenant_settings,
        POD_VS_RATECON_SUMMARY,
        summary_prompt_variables(cross_validation, pod_analysis),
        inline_fallback=render_inline_pod_vs_ratecon_summary_prompts(
            cross_validation,
            pod_analysis,
        ),
    )


def resolve_pod_vs_ratecon_semantic_match_prompts(
    tenant_settings: dict[str, Any] | None,
    field_type: str,
    pod_value: str,
    ratecon_value: str,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    from app.domain.pod_vs_ratecon_prompt_templates import (
        render_inline_pod_vs_ratecon_semantic_match_prompts,
        semantic_match_prompt_variables,
    )
    from app.domain.prompt_step_keys import POD_VS_RATECON_SEMANTIC_MATCH

    service = prompt_service or PromptService()
    return service.render_vision_step(
        tenant_settings,
        POD_VS_RATECON_SEMANTIC_MATCH,
        semantic_match_prompt_variables(field_type, pod_value, ratecon_value),
        inline_fallback=render_inline_pod_vs_ratecon_semantic_match_prompts(
            field_type,
            pod_value,
            ratecon_value,
        ),
    )
