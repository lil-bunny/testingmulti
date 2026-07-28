"""Per-tenant Ascend API auth (``tenants.settings.ascend``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class AscendSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email: str | None = None
    password_ciphertext: str | None = None
    access_token: str | None = None
    access_token_expires_at: str | None = None
    token_updated_at: str | None = None


def has_ascend_configured(cfg: dict[str, Any]) -> bool:
    block = cfg.get("ascend")
    if not isinstance(block, dict):
        return False
    model = AscendSettings.model_validate(block)
    return bool(
        str(model.email or "").strip() and str(model.password_ciphertext or "").strip()
    )
