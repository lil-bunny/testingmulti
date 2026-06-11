"""Resolve ``workflow_error_alerts`` from workflow payload tenant settings."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.logger import get_logger
from app.domain.load_tendering_settings import tenant_settings_root
from app.domain.tenant_settings.workflow_error_alerts import WorkflowErrorAlertSettings

logger = get_logger(__name__)


def resolve_workflow_error_alert_settings(
    state_or_data: Any,
    *,
    workflow_name: str,
) -> WorkflowErrorAlertSettings | None:
    """
    Load enabled alert settings for a workflow run.

    Per-workflow settings replace the root default when the workflow block defines
    ``workflow_error_alerts``.
    """
    root = tenant_settings_root(state_or_data)
    if not root:
        return None

    wf_name = (workflow_name or "").strip()
    if wf_name:
        wf_block = root.get(wf_name)
        if isinstance(wf_block, dict):
            parsed = _parse_block(wf_block.get("workflow_error_alerts"))
            if parsed is not None:
                return parsed

    return _parse_block(root.get("workflow_error_alerts"))


def _parse_block(raw: Any) -> WorkflowErrorAlertSettings | None:
    """Validate one settings block; return None when disabled or empty."""
    if not isinstance(raw, dict):
        return None
    try:
        settings = WorkflowErrorAlertSettings.model_validate(raw)
    except ValidationError:
        logger.warning("workflow_error_alerts settings invalid: %s", raw)
        return None
    if not settings.enabled or not settings.channels:
        return None
    return settings
