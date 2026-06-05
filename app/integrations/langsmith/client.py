"""LangSmith Hub pull with in-process cache and git fallback."""

from __future__ import annotations

from typing import Any

from langchain_core.prompts import BasePromptTemplate
from langsmith import Client

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.langsmith.errors import PromptUnavailableError
from app.integrations.langsmith.fallback import (
    hub_id_from_tenant_prompt_ref,
    load_fallback_prompt,
)
from app.integrations.langsmith.render import render_system_user
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt

logger = get_logger(__name__)


def _extract_commit_hash(prompt_obj: Any) -> str | None:
    metadata = getattr(prompt_obj, "metadata", None) or {}
    if isinstance(metadata, dict):
        for key in ("lc_hub_commit_hash", "commit_hash"):
            value = metadata.get(key)
            if value:
                return str(value)
    manifest = getattr(prompt_obj, "lc_hub_manifest", None)
    if isinstance(manifest, dict):
        value = manifest.get("lc_hub_commit_hash") or manifest.get("commit_hash")
        if value:
            return str(value)
    return None


class LangSmithPromptClient:
    """Pull managed prompts from LangSmith Hub; fall back to committed JSON on outage."""

    def __init__(self, *, client: Client | None = None) -> None:
        self._client = client
        self._cache: dict[str, BasePromptTemplate] = {}

    def _get_client(self) -> Client:
        if self._client is not None:
            return self._client
        api_key = (settings.LANGSMITH_API_KEY or "").strip()
        if not api_key:
            raise PromptUnavailableError("LANGSMITH_API_KEY is not configured")
        return Client(api_key=api_key)

    def load_and_render(
        self,
        tenant_prompt_ref: str,
        variables: dict[str, str],
    ) -> tuple[RenderedPrompt, PromptLoadMetadata]:
        ref = (tenant_prompt_ref or "").strip()
        hub_id = hub_id_from_tenant_prompt_ref(ref)
        template, source, commit_hash = self._load_template(ref, hub_id)
        rendered = render_system_user(template, variables)
        metadata = PromptLoadMetadata(
            source=source,
            tenant_prompt_ref=ref,
            commit_hash=commit_hash,
        )
        return rendered, metadata

    def _load_template(
        self,
        tenant_prompt_ref: str,
        hub_id: str,
    ) -> tuple[BasePromptTemplate, str, str | None]:
        if tenant_prompt_ref in self._cache:
            cached = self._cache[tenant_prompt_ref]
            return cached, "hub", _extract_commit_hash(cached)

        try:
            pulled = self._get_client().pull_prompt(tenant_prompt_ref)
            if not isinstance(pulled, BasePromptTemplate):
                raise TypeError(f"Hub ref {tenant_prompt_ref!r} is not a prompt template")
            commit_hash = _extract_commit_hash(pulled)
            self._cache[tenant_prompt_ref] = pulled
            return pulled, "hub", commit_hash
        except Exception as exc:
            logger.warning(
                "LangSmith pull_prompt failed ref=%s hub_id=%s: %s",
                tenant_prompt_ref,
                hub_id,
                exc,
            )

        try:
            fallback = load_fallback_prompt(hub_id)
            return fallback, "fallback", None
        except (FileNotFoundError, TypeError, ValueError) as fb_exc:
            raise PromptUnavailableError(
                f"prompt unavailable for hub id {hub_id!r}: hub error and no fallback"
            ) from fb_exc
