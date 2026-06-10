"""User identity returned by freightx-api ``GET /api/v1/auth/me``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiUser(BaseModel):
    id: str
    name: str
    email: str
    platform_role: str | None = Field(default=None, alias="platformRole")
    tenant_role: str | None = Field(default=None, alias="tenantRole")
    tenant_ids: list[str] = Field(default_factory=list, alias="tenantIds")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    tenant_site_ids: list[str] = Field(default_factory=list, alias="tenantSiteIds")
    enabled_processes: list[str] = Field(
        default_factory=list, alias="enabledProcesses"
    )
    permissions: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def has_permission(self, name: str) -> bool:
        return name in self.permissions
