"""Resolve LLM gateway credentials for a workflow.

Callers depend on this boundary instead of environment variable names so the
backing store can move to per-tenant credentials without changing LLM clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class LLMCredentials:
    base_url: str
    api_key: str


_WORKFLOW_API_KEY_GETTERS: dict[str, Callable[[], str]] = {
    "pod_lifecycle": lambda: settings.LLM_POD_LIFECYCLE_API_KEY,
    "driver_assignment": lambda: settings.LLM_DRIVER_ASSIGNMENT_API_KEY,
    "appointment_scheduling": lambda: settings.LLM_APPOINTMENT_SCHEDULING_API_KEY,
    "load_tendering": lambda: settings.LLM_LOAD_TENDERING_API_KEY,
}


def resolve_llm_credentials(
    *,
    workflow_name: str,
    tenant_slug: str | None = None,
) -> LLMCredentials:
    """Return credentials for one workflow.

    ``tenant_slug`` is intentionally part of the stable interface. The initial
    environment-backed implementation does not use it; a tenant-backed
    resolver can do so without changing callers.
    """
    del tenant_slug
    normalized_name = (workflow_name or "").strip()
    try:
        api_key = _WORKFLOW_API_KEY_GETTERS[normalized_name]()
    except KeyError as exc:
        raise ValueError(f"Unsupported LLM workflow: {normalized_name!r}") from exc
    return LLMCredentials(
        base_url=(settings.LLM_BASE_URL or "").strip(),
        api_key=(api_key or "").strip(),
    )
