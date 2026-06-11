"""Types for LangSmith prompt load and render."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PromptSource = Literal["hub", "fallback"]


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str


@dataclass(frozen=True)
class PromptLoadMetadata:
    source: PromptSource
    tenant_prompt_ref: str
    commit_hash: str | None = None


@dataclass(frozen=True)
class PromptTraceMetadata:
    """Prompt provenance for LangSmith LLM spans and activity logs (ADR 0009)."""

    prompt_step_key: str
    tenant_prompt_ref: str
    prompt_source: PromptSource
    prompt_commit_hash: str | None = None

    @classmethod
    def from_load(
        cls,
        step_key: str,
        load: PromptLoadMetadata,
    ) -> PromptTraceMetadata:
        return cls(
            prompt_step_key=step_key,
            tenant_prompt_ref=load.tenant_prompt_ref,
            prompt_source=load.source,
            prompt_commit_hash=load.commit_hash,
        )

    def to_langsmith_metadata(self) -> dict[str, str | None]:
        return {
            "prompt_step_key": self.prompt_step_key,
            "tenant_prompt_ref": self.tenant_prompt_ref,
            "prompt_source": self.prompt_source,
            "prompt_commit_hash": self.prompt_commit_hash,
        }
