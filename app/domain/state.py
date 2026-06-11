from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class WorkflowState(BaseModel):
    tenant_id: str  # tenants.id (UUID)
    tenant_slug: str  # tenants.slug / TENANT_CONFIGS key
    execution_id: str

    data: Dict[str, Any] = Field(default_factory=dict)


def workflow_state_data(state_or_data: Any) -> dict[str, Any]:
    """Return ``state.data`` or a plain Celery/graph payload dict; else ``{}``."""
    if isinstance(state_or_data, dict):
        return state_or_data
    data = getattr(state_or_data, "data", None)
    if isinstance(data, dict):
        return data
    return {}


def tenant_slug_from_payload(data: Any) -> str | None:
    """``tenant_slug`` from workflow payload dict (``state.data`` shape), or ``None``."""
    if not isinstance(data, dict):
        return None
    slug = data.get("tenant_slug")
    if slug is not None and str(slug).strip():
        return str(slug).strip()
    return None
