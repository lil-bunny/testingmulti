"""Appointment scheduling tenant settings helpers."""

from __future__ import annotations

import os
from typing import Any

from app.core.config import settings


def skip_ascend_writes_enabled(tenant_settings: dict[str, Any] | None) -> bool:
    """True when Ascend HTTP writes should be skipped (dry-run payload + activity only)."""
    env_raw = os.environ.get("APPOINTMENT_SCHEDULING_SKIP_ASCEND_WRITES")
    if env_raw is not None and str(env_raw).strip():
        return str(env_raw).strip().lower() in {"1", "true", "yes", "on"}

    if not isinstance(tenant_settings, dict):
        return True

    block = tenant_settings.get("appointment_scheduling")
    if not isinstance(block, dict):
        return True

    if "skip_ascend_writes" in block:
        return bool(block.get("skip_ascend_writes"))

    # ponytail: default safe until team enables Ascend in prod
    _ = settings
    return True
