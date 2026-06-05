"""Load LangChain-serialized prompt manifests from ``prompts/fallbacks/``."""

from __future__ import annotations

from pathlib import Path

from langchain_core.load.load import loads
from langchain_core.prompts import BasePromptTemplate

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FALLBACKS_DIR = _REPO_ROOT / "prompts" / "fallbacks"


def hub_id_from_tenant_prompt_ref(tenant_prompt_ref: str) -> str:
    """Strip trailing ``:tag`` to get the Hub id used for fallback paths."""
    ref = (tenant_prompt_ref or "").strip()
    if ":" in ref:
        return ref.rsplit(":", 1)[0]
    return ref


def fallback_path_for_hub_id(hub_id: str) -> Path:
    return _FALLBACKS_DIR / f"{hub_id.strip()}.json"


def load_fallback_prompt(hub_id: str) -> BasePromptTemplate:
    path = fallback_path_for_hub_id(hub_id)
    if not path.is_file():
        raise FileNotFoundError(f"no fallback prompt at {path}")
    loaded = loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, BasePromptTemplate):
        raise TypeError(f"fallback at {path} is not a prompt template")
    return loaded
