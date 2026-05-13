"""E2E targets — edit the module-level constants here instead of using environment variables.

``UNIPILE_WEBHOOK_SECRET`` and ``DATABASE_URL`` still come from the app ``settings`` / ``.env``
(loaded in ``conftest``) so secrets stay out of source control.
"""

from __future__ import annotations

# --- edit these for local E2E ---
E2E_API_BASE_URL: str = "http://127.0.0.1:8000"

# Turvo shipment id used for lifecycle seeding assertions and ``documents`` / ``document_analysis`` queries.
E2E_POD_LIFECYCLE_SHIPMENT_ID: str = "1000324868"


def e2e_api_base_url() -> str:
    return (E2E_API_BASE_URL or "").strip()


def e2e_unipile_webhook_secret_configured() -> bool:
    from app.core.config import settings

    return bool((getattr(settings, "UNIPILE_WEBHOOK_SECRET", None) or "").strip())


def pod_email_e2e_ready() -> tuple[bool, str]:
    if not e2e_api_base_url():
        return False, "set E2E_API_BASE_URL in tests/e2e/config.py"
    if not e2e_unipile_webhook_secret_configured():
        return False, "set UNIPILE_WEBHOOK_SECRET for Bearer auth (must match the API process)"
    sid = (E2E_POD_LIFECYCLE_SHIPMENT_ID or "").strip()
    if not sid:
        return False, "set E2E_POD_LIFECYCLE_SHIPMENT_ID in tests/e2e/config.py"
    return True, ""
