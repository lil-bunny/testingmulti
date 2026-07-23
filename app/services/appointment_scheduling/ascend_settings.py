"""Load full appointment scheduling settings (including credentials) from DB."""

from __future__ import annotations

from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.services.tenants_service import TenantsService


def load_appointment_scheduling_settings(
    tenant_slug: str,
    *,
    tenants_service: TenantsService | None = None,
) -> T3raAppointmentSchedulingSettings:
    slug = str(tenant_slug or "").strip()
    row = (tenants_service or TenantsService()).get_by_slug(slug) or {}
    settings = row.get("settings") if isinstance(row.get("settings"), dict) else {}
    block = settings.get("appointment_scheduling")
    if not isinstance(block, dict):
        block = {}
    return T3raAppointmentSchedulingSettings.model_validate(block)


__all__ = ("load_appointment_scheduling_settings",)
