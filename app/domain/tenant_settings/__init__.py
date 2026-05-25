"""Tenant-specific ``tenants.settings`` contracts and shared email recipient helpers."""

from app.domain.tenant_settings.email_recipients import (
    EmailRecipients,
    coerce_email_list,
    email_recipients_from_action_cfg,
    unipile_recipients_from_addresses,
)
from app.domain.tenant_settings.gelita import GelitaTenantSettings
from app.domain.tenant_settings.registry import (
    normalize_tenant_settings_dict,
    parse_tenant_settings,
)

__all__ = [
    "EmailRecipients",
    "GelitaTenantSettings",
    "coerce_email_list",
    "email_recipients_from_action_cfg",
    "normalize_tenant_settings_dict",
    "parse_tenant_settings",
    "unipile_recipients_from_addresses",
]
