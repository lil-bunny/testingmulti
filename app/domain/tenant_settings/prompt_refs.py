"""Resolve tenant prompt refs from flat or nested ``prompts`` JSON."""

from __future__ import annotations

from typing import Any


def tenant_prompt_ref(prompts: dict[str, Any], step_key: str) -> str:
    """Flat key first (Gelita / legacy DB), then nested ``group.leaf`` lookup."""
    flat = prompts.get(step_key)
    if isinstance(flat, str) and flat.strip():
        return flat.strip()
    if "." not in step_key:
        return ""
    group, _, leaf = step_key.partition(".")
    block = prompts.get(group)
    if isinstance(block, dict):
        return str(block.get(leaf) or "").strip()
    return ""
