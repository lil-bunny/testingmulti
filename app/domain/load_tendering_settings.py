"""Read ``load_tendering`` action config from workflow state / Celery payload."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.domain.tenant_settings.gelita import (
    GelitaEscalateTenderSettings,
    GelitaSendTenderEmailSettings,
    GelitaTenantSettings,
)
from app.services.tender_service import TenderService
from app.domain.state import workflow_state_data

LOAD_TENDERING_SETTINGS_KEY = "load_tendering"
_LOAD_TYPE_BUCKETS = frozenset({"ltl", "ftl"})

# Fixed Unipile senders for Gelita — live at ``tenants.settings`` root (not per ltl/ftl).
_SHARED_UNIPILE_ACCOUNT_KEYS = frozenset(
    {
        "ana_at_gelita_account_id",
        "ana_gelita_at_freightx_ai_account_id",
    }
)


def tenant_settings_root(state_or_data: Any) -> dict[str, Any]:
    """
    Return parsed ``tenant_settings`` from a ``WorkflowState``-like object or payload dict.

    Supports ``state.data``, plain dict payloads, and objects with a ``data`` attribute.
    """
    if isinstance(state_or_data, dict):
        raw = state_or_data.get("tenant_settings")
    else:
        data = getattr(state_or_data, "data", None)
        if isinstance(data, dict):
            raw = data.get("tenant_settings")
        else:
            raw = None
    if isinstance(raw, dict):
        return raw
    return {}


def load_tendering_settings_root(state_or_data: Any) -> dict[str, Any]:
    """Return the ``load_tendering`` subtree of ``tenant_settings``."""
    root = tenant_settings_root(state_or_data)
    block = root.get(LOAD_TENDERING_SETTINGS_KEY)
    if isinstance(block, dict):
        return block
    return {}


def shared_unipile_account_settings(state_or_data: Any) -> dict[str, Any]:
    """
    Gelita-wide Unipile account ids (two fixed senders).

    Read from ``tenants.settings`` root, with optional override under
    ``load_tendering`` for the same keys.
    """
    out: dict[str, Any] = {}
    tenant_root = tenant_settings_root(state_or_data)
    for key in _SHARED_UNIPILE_ACCOUNT_KEYS:
        if key in tenant_root:
            out[key] = tenant_root[key]
    lt = load_tendering_settings_root(state_or_data)
    for key in _SHARED_UNIPILE_ACCOUNT_KEYS:
        if key in lt:
            out[key] = lt[key]
    return out


def is_ftl_load_type(load_type: str | None) -> bool:
    """True when tender routing should use the ``ftl`` settings bucket."""
    return str(load_type or "").strip().upper() == "FTL"


def load_type_bucket(load_type: str | None) -> str:
    """Settings branch name: ``ltl`` or ``ftl``."""
    return "ftl" if is_ftl_load_type(load_type) else "ltl"


def load_type_from_pallet_totals(
    products_calc: list[dict[str, Any]],
    *,
    pallet_threshold: int,
) -> str:
    """
    Gelita order-level load type from summed per-product pallet counts (W3).

    Returns ``FTL`` when total pallets exceed ``pallet_threshold``, else ``LTL``.
    Each ``products_calc`` entry may use ``pallets_count`` or ``pallets``.
    """
    total_pallets = 0
    for item in products_calc:
        raw = item.get("pallets_count", item.get("pallets"))
        if raw is None:
            continue
        try:
            total_pallets += int(raw)
        except (TypeError, ValueError):
            continue
    return "FTL" if total_pallets > pallet_threshold else "LTL"


def resolve_load_type(state_or_data: Any) -> str:
    """
    Normalize load type (``LTL`` / ``FTL``) from ``state.data['tender']`` or DB fallback.
    """
    from app.domain.load_tendering_state import load_type_from_data

    data = workflow_state_data(state_or_data)
    from_tender = load_type_from_data(data)
    if from_tender:
        return from_tender.upper()
    raw = str(data.get("load_type") or "").strip()
    if raw:
        return raw.upper()
    tender_id = str(data.get("tender_id") or "").strip()
    tenant_id = str(data.get("tenant_id") or "").strip()
    if not tender_id or not tenant_id:
        return ""
    tender_service = TenderService()
    bundle = tender_service.read_order(tenant_id=tenant_id, tender_id=tender_id)
    if not bundle:
        return ""
    return str(bundle["tender"].get("load_type") or "").strip().upper()


def action_settings(
    state_or_data: Any,
    action: str,
    *,
    load_type: str | None = None,
) -> dict[str, Any]:
    """
    Return config for one load-tendering action.

    Load-type-specific nodes live under ``load_tendering.ltl.<action>`` or
    ``load_tendering.ftl.<action>``. Shared config (e.g. ``tender_calculate``)
    stays at ``load_tendering.<action>``.

    Unipile sender account ids are merged from ``tenants.settings`` root (and
    optional ``load_tendering`` overrides) into every action block.
    """
    lt = load_tendering_settings_root(state_or_data)
    shared_accounts = shared_unipile_account_settings(state_or_data)

    block: dict[str, Any] | None = None
    if load_type is not None and str(load_type).strip():
        branch = lt.get(load_type_bucket(load_type))
        if isinstance(branch, dict):
            candidate = branch.get(action)
            if isinstance(candidate, dict):
                block = candidate
    if block is None:
        candidate = lt.get(action)
        if isinstance(candidate, dict) and action not in _LOAD_TYPE_BUCKETS:
            block = candidate

    if block is None:
        return dict(shared_accounts)
    return {**shared_accounts, **block}


def parse_gelita_tenant_settings(state_or_data: Any) -> GelitaTenantSettings:
    """Validate full Gelita ``tenant_settings`` blob; raises ``ValidationError`` on mismatch."""
    return GelitaTenantSettings.model_validate(tenant_settings_root(state_or_data))


def gelita_send_tender_email_settings(
    state_or_data: Any,
    *,
    load_type: str | None,
) -> GelitaSendTenderEmailSettings | None:
    """Parse ``send_tender_email`` action block for Gelita; ``None`` if validation fails."""
    cfg = action_settings(state_or_data, "send_tender_email", load_type=load_type)
    try:
        return GelitaSendTenderEmailSettings.model_validate(cfg)
    except ValidationError:
        return None


def gelita_escalate_tender_settings(
    state_or_data: Any,
    *,
    load_type: str | None,
) -> GelitaEscalateTenderSettings | None:
    """Parse ``escalate_tender`` action block for Gelita; ``None`` if validation fails."""
    cfg = action_settings(state_or_data, "escalate_tender", load_type=load_type)
    try:
        return GelitaEscalateTenderSettings.model_validate(cfg)
    except ValidationError:
        return None
