"""Resolve tenant prompt refs and render LangSmith-managed LLM steps.

Prompts load from Hub, then ``prompts/fallbacks/*.json`` — never from inline
Python template strings.
"""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.prompt_step_keys import resolve_prompt_ref
from app.integrations.langsmith import (
    LangSmithPromptClient,
    MissingTenantPromptRefError,
    PromptLoadMetadata,
    PromptUnavailableError,
    RenderedPrompt,
)

logger = get_logger(__name__)


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

    def render_json_managed_step(
        self,
        tenant_settings: dict[str, Any] | None,
        prompt_step_key: str,
        hub_id: str,
        variables: dict[str, str],
    ) -> tuple[RenderedPrompt, PromptLoadMetadata]:
        """
        Render a managed prompt from Hub (with JSON fallback) or committed JSON only.

        When the tenant has no ``prompts`` ref for ``prompt_step_key``, loads
        ``prompts/fallbacks/{hub_id}.json``. Raises ``PromptUnavailableError`` if
        JSON is missing or invalid (no inline Python prompt fallback).
        """
        from app.integrations.langsmith.fallback import load_fallback_prompt
        from app.integrations.langsmith.render import render_system_user

        settings_dict = tenant_settings if isinstance(tenant_settings, dict) else {}
        prompts = settings_dict.get("prompts") or {}
        tenant_prompt_ref = resolve_prompt_ref(prompts, prompt_step_key)
        if tenant_prompt_ref:
            return self.render_step(settings_dict, prompt_step_key, variables)

        try:
            template = load_fallback_prompt(hub_id)
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise PromptUnavailableError(
                f"prompt unavailable for hub id {hub_id!r}: no tenant ref and no JSON fallback"
            ) from exc

        rendered = render_system_user(template, variables)
        logger.debug(
            "json managed prompt fallback step=%s hub_id=%s (no tenant ref)",
            prompt_step_key,
            hub_id,
        )
        return (
            rendered,
            PromptLoadMetadata(
                source="fallback",
                tenant_prompt_ref=hub_id,
                commit_hash=None,
            ),
        )


def _tenant_settings_dict(
    tenant_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    return tenant_settings if isinstance(tenant_settings, dict) else {}


def resolve_pod_pdf_prompts(
    tenant_settings: dict[str, Any] | None,
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    """Render POD whole-document PDF extraction prompts (no template variables)."""
    from app.domain.prompt_step_keys import POD_PDF_EXTRACTION

    service = prompt_service or PromptService()
    return service.render_step(
        _tenant_settings_dict(tenant_settings),
        POD_PDF_EXTRACTION,
        {},
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


def resolve_appointment_scheduling_optimization_prompts(
    tenant_settings: dict[str, Any] | None,
    variables: dict[str, str],
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    from app.domain.prompt_hub_refs import APPOINTMENT_SCHEDULING_OPTIMIZATION_PROMPT
    from app.domain.prompt_step_keys import APPOINTMENT_SCHEDULING_OPTIMIZATION

    service = prompt_service or PromptService()
    return service.render_json_managed_step(
        tenant_settings,
        APPOINTMENT_SCHEDULING_OPTIMIZATION,
        APPOINTMENT_SCHEDULING_OPTIMIZATION_PROMPT,
        variables,
    )


def resolve_appointment_scheduling_customer_reply_prompts(
    tenant_settings: dict[str, Any] | None,
    variables: dict[str, str],
    *,
    prompt_service: PromptService | None = None,
) -> tuple[RenderedPrompt, PromptLoadMetadata]:
    from app.domain.prompt_hub_refs import APPOINTMENT_SCHEDULING_CUSTOMER_REPLY_PROMPT
    from app.domain.prompt_step_keys import APPOINTMENT_SCHEDULING_CUSTOMER_REPLY

    service = prompt_service or PromptService()
    return service.render_json_managed_step(
        tenant_settings,
        APPOINTMENT_SCHEDULING_CUSTOMER_REPLY,
        APPOINTMENT_SCHEDULING_CUSTOMER_REPLY_PROMPT,
        variables,
    )

