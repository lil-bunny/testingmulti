"""Root-cause vs downstream relationships for business catalog errors."""

from __future__ import annotations

from typing import Any

from app.domain.error_catalog import BusinessError

# Ancestor code -> dependent codes suppressed when the ancestor is present in scope.
BUSINESS_ERROR_DEPENDENCIES: dict[str, frozenset[str]] = {
    BusinessError.MISSING_DELIVERY_ADDRESS.value: frozenset(
        {BusinessError.MISSING_CUSTOMER_NAME.value}
    ),
    BusinessError.MISSING_PACK_CODE.value: frozenset(
        {
            BusinessError.MISSING_QTY_PER_UNIT.value,
            BusinessError.MISSING_TOTAL_QTY.value,
            BusinessError.MISSING_UNIT_DIMS.value,
        }
    ),
}

# Format-kwarg keys that identify the same failure instance for a given code.
ERROR_SCOPE_KEYS: dict[str, tuple[str, ...]] = {
    BusinessError.MISSING_DELIVERY_ADDRESS.value: ("del_code",),
    BusinessError.MISSING_CUSTOMER_NAME.value: ("del_code",),
    BusinessError.MISSING_PACK_CODE.value: ("pack_code", "tender_product_id"),
    BusinessError.MISSING_QTY_PER_UNIT.value: ("pack_code", "tender_product_id"),
    BusinessError.MISSING_TOTAL_QTY.value: ("pack_code", "tender_product_id"),
    BusinessError.MISSING_UNIT_DIMS.value: ("pack_code", "tender_product_id"),
}


def warning_code(warning: dict[str, Any]) -> str:
    return str(warning.get("code") or "").strip()


def warning_context(warning: dict[str, Any]) -> dict[str, str]:
    raw = warning.get("context")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _shared_scope_keys(ancestor_code: str, dependent_code: str) -> tuple[str, ...]:
    ancestor_keys = ERROR_SCOPE_KEYS.get(ancestor_code, ())
    dependent_keys = ERROR_SCOPE_KEYS.get(dependent_code, ())
    return tuple(key for key in ancestor_keys if key in dependent_keys)


def scopes_match(
    *,
    ancestor_code: str,
    ancestor_context: dict[str, str],
    dependent_code: str,
    dependent_context: dict[str, str],
) -> bool:
    """True when ``dependent`` should be treated as downstream of ``ancestor``."""
    shared_keys = _shared_scope_keys(ancestor_code, dependent_code)
    if not shared_keys:
        return True

    ancestor_has_scope = any(
        str(ancestor_context.get(key) or "").strip() for key in shared_keys
    )
    dependent_has_scope = any(
        str(dependent_context.get(key) or "").strip() for key in shared_keys
    )
    if not ancestor_has_scope or not dependent_has_scope:
        return True

    return all(
        str(ancestor_context.get(key) or "").strip()
        == str(dependent_context.get(key) or "").strip()
        for key in shared_keys
    )


def is_suppressed_by_ancestor(
    *,
    ancestor_code: str,
    ancestor_context: dict[str, str],
    dependent_code: str,
    dependent_context: dict[str, str],
) -> bool:
    """True when ``dependent_code`` is downstream of ``ancestor_code`` in scope."""
    dependents = BUSINESS_ERROR_DEPENDENCIES.get(ancestor_code, frozenset())
    if dependent_code not in dependents:
        return False
    return scopes_match(
        ancestor_code=ancestor_code,
        ancestor_context=ancestor_context,
        dependent_code=dependent_code,
        dependent_context=dependent_context,
    )


def is_suppressed_by_warnings(
    warnings: list[dict[str, Any]],
    *,
    code: str,
    context: dict[str, str] | None = None,
) -> bool:
    """True when an existing warning already covers this code/context pair."""
    dependent_context = context or {}
    dependent_code = str(code or "").strip()
    if not dependent_code:
        return False

    for warning in warnings:
        ancestor_code = warning_code(warning)
        if not ancestor_code:
            continue
        if is_suppressed_by_ancestor(
            ancestor_code=ancestor_code,
            ancestor_context=warning_context(warning),
            dependent_code=dependent_code,
            dependent_context=dependent_context,
        ):
            return True
    return False
