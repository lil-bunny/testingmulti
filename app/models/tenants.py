"""Known ``tenants.slug`` values and ``TENANT_CONFIGS`` graph keys."""

from __future__ import annotations

from enum import StrEnum


class TenantSlug(StrEnum):
    """Canonical tenant slugs; keep in sync with ``app/configs/tenant_configs.py`` keys."""

    T3RA = "t3ra"
    GELITA = "gelita"
