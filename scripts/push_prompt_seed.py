#!/usr/bin/env python3
"""Bootstrap: push managed prompts from ``prompts/fallbacks/`` to LangSmith Hub.

Source of truth is the LangChain-serialized JSON under ``prompts/fallbacks/``.
Requires ``LANGSMITH_API_KEY`` in ``.env`` (optional ``LANGSMITH_PROMPT_OWNER``).

Push all fallbacks to Hub::

    uv run python scripts/push_prompt_seed.py
    uv run python scripts/push_prompt_seed.py --prompt all

Push one prompt (CLI choice → ``prompts/fallbacks/<hub-id>.json``)::

    uv run python scripts/push_prompt_seed.py --prompt carrier-ack
    uv run python scripts/push_prompt_seed.py --prompt driver-details
    uv run python scripts/push_prompt_seed.py --prompt pod
    uv run python scripts/push_prompt_seed.py --prompt pod-attachment-classifier
    uv run python scripts/push_prompt_seed.py --prompt ratecon
    uv run python scripts/push_prompt_seed.py --prompt pod-vs-ratecon
    uv run python scripts/push_prompt_seed.py --prompt pod-vs-ratecon-semantic

Refresh local fallbacks from Hub (opposite direction)::

    uv run python scripts/sync_prompt_fallbacks.py --ref pod-page-extraction:staging
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client
from langsmith.utils import LangSmithConflictError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.core.config import settings  # noqa: E402
from app.domain.prompt_hub_refs import (  # noqa: E402
    CARRIER_ACK_CLASSIFY_PROMPT,
    DRIVER_DETAILS_EXTRACT_PROMPT,
    POD_ATTACHMENT_CLASSIFIER_PROMPT,
    POD_PAGE_EXTRACTION_PROMPT,
    POD_VS_RATECON_SEMANTIC_MATCH_PROMPT,
    POD_VS_RATECON_SUMMARY_PROMPT,
    RATECON_PAGE_EXTRACTION_PROMPT,
    hub_prompt_id,
)
from app.integrations.langsmith.fallback import load_fallback_prompt  # noqa: E402

# CLI --prompt choices → Hub prompt names (fallback file stems).
_PROMPT_TARGETS: dict[str, str] = {
    "carrier-ack": CARRIER_ACK_CLASSIFY_PROMPT,
    "driver-details": DRIVER_DETAILS_EXTRACT_PROMPT,
    "pod": POD_PAGE_EXTRACTION_PROMPT,
    "pod-attachment-classifier": POD_ATTACHMENT_CLASSIFIER_PROMPT,
    "ratecon": RATECON_PAGE_EXTRACTION_PROMPT,
    "pod-vs-ratecon": POD_VS_RATECON_SUMMARY_PROMPT,
    "pod-vs-ratecon-semantic": POD_VS_RATECON_SEMANTIC_MATCH_PROMPT,
}


def _seed_prompt_from_fallback(hub_id: str) -> ChatPromptTemplate:
    """Load a Hub seed template from ``prompts/fallbacks/<hub_id>.json``."""
    loaded = load_fallback_prompt(hub_id)
    if not isinstance(loaded, ChatPromptTemplate):
        raise TypeError(
            f"fallback for {hub_id!r} must be ChatPromptTemplate, got {type(loaded).__name__}"
        )
    return loaded


def _langsmith_client() -> Client:
    api_key = (settings.LANGSMITH_API_KEY or "").strip()
    if not api_key:
        print(
            "LANGSMITH_API_KEY is not set. Add it to .env or export it, then retry.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return Client(api_key=api_key)


def _hub_id(prompt_name: str) -> str:
    return hub_prompt_id(prompt_name, owner=settings.LANGSMITH_PROMPT_OWNER)


def _ensure_commit_tags(
    client: Client,
    prompt_name: str,
    *,
    tags: list[str],
) -> None:
    """Apply commit tags when push is a no-op (unchanged content)."""
    commits = list(client.list_prompt_commits(prompt_name))
    if not commits:
        print(f"No commits found for {prompt_name}; cannot tag")
        return
    latest = commits[0]
    owner_and_name = f"{latest.owner}/{latest.repo}"
    for tag in tags:
        try:
            client._create_commit_tags(owner_and_name, str(latest.id), tag)
            print(f"Tagged {prompt_name}:{tag}")
        except LangSmithConflictError:
            print(f"Tag already present {prompt_name}:{tag}")


def _ensure_repo_tags(client: Client, prompt_name: str, *, tags: list[str]) -> None:
    """Ensure Hub repo tags include required labels (e.g. ChatPromptTemplate)."""
    desired = [t for t in tags if t]
    if not desired:
        return
    try:
        client.update_prompt(prompt_name, tags=desired)
        print(f"Updated repo tags {prompt_name}: {desired}")
    except Exception as exc:
        print(f"Failed to update repo tags {prompt_name}: {exc}", file=sys.stderr)


def push_prompt(client: Client, prompt_name: str, template: ChatPromptTemplate) -> str:
    prompt_id = _hub_id(prompt_name)
    # Repo tags (Hub UI / list_prompts). Commit tags are separate version pins.
    repo_tags = ["staging", "ChatPromptTemplate"]
    commit_tags = ["staging", "production"]
    try:
        url = client.push_prompt(
            prompt_id,
            object=template,
            tags=repo_tags,
            commit_tags=commit_tags,
            commit_description="FreightX managed prompt from prompts/fallbacks",
        )
    except LangSmithConflictError:
        print(f"Skipped {prompt_id}: unchanged since latest commit")
        _ensure_commit_tags(client, prompt_name, tags=commit_tags)
        _ensure_repo_tags(client, prompt_name, tags=repo_tags)
        return prompt_id
    print(f"Pushed {prompt_id} -> {url}")
    _ensure_repo_tags(client, prompt_name, tags=repo_tags)
    return prompt_id


def _resolve_targets(choice: str) -> list[str]:
    if choice == "all":
        return list(_PROMPT_TARGETS.values())
    return [_PROMPT_TARGETS[choice]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        choices=[*sorted(_PROMPT_TARGETS), "all"],
        default="all",
        help="Which prompt(s) to push from prompts/fallbacks (default: all)",
    )
    args = parser.parse_args()
    client = _langsmith_client()

    for prompt_name in _resolve_targets(args.prompt):
        push_prompt(client, prompt_name, _seed_prompt_from_fallback(prompt_name))

    print("Tag production in the LangSmith UI when ready for prod tenants.")
    if not (settings.LANGSMITH_PROMPT_OWNER or "").strip():
        print(
            "Tenant settings should use refs like "
            f"{POD_PAGE_EXTRACTION_PROMPT}:staging and "
            f"{POD_ATTACHMENT_CLASSIFIER_PROMPT}:staging (no owner prefix)."
        )


if __name__ == "__main__":
    main()
