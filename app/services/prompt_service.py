"""Resolve tenant prompt refs and render LangSmith-managed LLM steps."""

from __future__ import annotations

from typing import Any

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
        prompts = tenant_settings.get("prompts") or {}
        if not isinstance(prompts, dict):
            prompts = {}
        tenant_prompt_ref = str(prompts.get(prompt_step_key) or "").strip()
        if not tenant_prompt_ref:
            raise MissingTenantPromptRefError(
                f"missing tenant prompt ref for step {prompt_step_key!r}"
            )
        return self._prompt_client.load_and_render(tenant_prompt_ref, variables)
