"""Read ``load_tendering`` action config from workflow state / Celery payload."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.logger import get_logger
from app.domain.error_catalog import SystemError
from app.domain.gelita.routing_guide import GELITA_MAX_CARRIER_ATTEMPTS
from app.domain.state import workflow_state_data
from app.domain.tenant_settings.gelita import (
    GelitaDomesticDeliverySettings,
    GelitaEscalateTenderSettings,
    GelitaSendTenderEmailSettings,
    GelitaSkippedPackCodesSettings,
    GelitaTenderCalculateSettings,
    GelitaTenantSettings,
)
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService

logger = get_logger(__name__)

LOAD_TENDERING_SETTINGS_KEY = "load_tendering"
_LOAD_TYPE_BUCKETS = frozenset({"ltl", "ftl"})

# Fixed Unipile sender for Gelita — lives at ``tenants.settings`` root (not per ltl/ftl).
_SHARED_UNIPILE_ACCOUNT_KEYS = frozenset(
    {"ana_at_gelita_account_id", "unipile_sent_folder_id"}
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
    Gelita-wide Unipile account id.

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
    pallet_threshold: int | None = None,
) -> str:
    """
    Gelita order-level load type from per-product pallet counts (W3).

    When entries include ``pallet_profile`` and ``pallet_threshold``, pallet counts
    are bucketed per profile; ``FTL`` when any bucket exceeds its threshold.
    Otherwise compares the order total to ``pallet_threshold`` (default 8).
    """
    fallback_threshold = 8 if pallet_threshold is None else pallet_threshold
    per_profile: dict[str, tuple[int, int]] = {}
    total_pallets = 0

    for item in products_calc:
        raw = item.get("pallets_count", item.get("pallets"))
        if raw is None:
            continue
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        total_pallets += count

        profile_key = item.get("pallet_profile")
        line_threshold = item.get("pallet_threshold")
        if profile_key is None or line_threshold is None:
            continue
        try:
            threshold = int(line_threshold)
        except (TypeError, ValueError):
            threshold = fallback_threshold
        prev, _ = per_profile.get(str(profile_key), (0, threshold))
        per_profile[str(profile_key)] = (prev + count, threshold)

    if per_profile:
        for count, threshold in per_profile.values():
            if count > threshold:
                return "FTL"
        return "LTL"

    return "FTL" if total_pallets > fallback_threshold else "LTL"


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


def gelita_tender_calculate_settings(
    state_or_data: Any,
) -> GelitaTenderCalculateSettings | None:
    """Parse ``tender_calculate`` action block for Gelita; ``None`` if validation fails."""
    cfg = action_settings(state_or_data, "tender_calculate")
    try:
        return GelitaTenderCalculateSettings.model_validate(cfg)
    except ValidationError:
        return None


def _system_error_for_tender_calculate_validation(exc: ValidationError) -> SystemError:
    """Map Pydantic ``tender_calculate`` field errors to tenant settings system errors."""
    top_fields: set[str] = set()
    for err in exc.errors():
        loc = err.get("loc") or ()
        if loc and isinstance(loc[0], str):
            top_fields.add(loc[0])
    if top_fields == {"gelita_pickup_address"}:
        return SystemError.MISSING_TENANT_SETTINGS_GELITA_PICKUP_ADDRESS
    if "pallet_profiles" in top_fields:
        return SystemError.MISSING_TENANT_SETTINGS_PALLET_PROFILES
    if "gelita_pickup_address" in top_fields:
        return SystemError.MISSING_TENANT_SETTINGS_GELITA_PICKUP_ADDRESS
    return SystemError.MISSING_TENANT_SETTINGS_PALLET_PROFILES


def require_gelita_tender_calculate_settings(
    state_or_data: Any,
) -> GelitaTenderCalculateSettings:
    """Parse ``tender_calculate`` for Gelita; raises mapped ``WorkflowException`` on failure."""
    cfg = action_settings(state_or_data, "tender_calculate")
    try:
        return GelitaTenderCalculateSettings.model_validate(cfg)
    except ValidationError as exc:
        system_error = _system_error_for_tender_calculate_validation(exc)
        raise WorkflowException(system_error) from None


def routing_guide_max_attempts(state_or_data: Any) -> int:
    default = GELITA_MAX_CARRIER_ATTEMPTS
    try:
        settings = parse_gelita_tenant_settings(state_or_data)
        raw = settings.load_tendering.ftl.max_attempts
    except ValidationError:
        return default
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    if value < 1:
        return default
    if value > default:
        logger.warning(
            "routing_guide_max_attempts exceeds enum ceiling configured=%s ceiling=%s; clamping",
            value,
            default,
        )
        return default
    return value


def gelita_domestic_delivery_settings(
    state_or_data: Any,
) -> GelitaDomesticDeliverySettings | None:
    """Parse ``domestic_delivery`` block for Gelita; ``None`` if validation fails."""
    block = load_tendering_settings_root(state_or_data).get("domestic_delivery")
    try:
        return GelitaDomesticDeliverySettings.model_validate(block)
    except ValidationError:
        return None


def gelita_skipped_pack_codes_settings(
    state_or_data: Any,
) -> GelitaSkippedPackCodesSettings:
    """Parse ``skipped_pack_codes`` for Gelita; empty when missing or invalid."""
    block = load_tendering_settings_root(state_or_data).get("skipped_pack_codes")
    if not isinstance(block, dict):
        return GelitaSkippedPackCodesSettings()
    try:
        return GelitaSkippedPackCodesSettings.model_validate(block)
    except ValidationError:
        return GelitaSkippedPackCodesSettings()
