"""Collect business catalog gaps on soft-fail paths without failing the graph."""

from __future__ import annotations

from html import escape
from typing import Any

from app.domain.business_error_dependencies import (
    is_suppressed_by_ancestor,
    is_suppressed_by_warnings,
    warning_code,
    warning_context,
)
from app.domain.error_catalog import BusinessError

TENDER_BUSINESS_WARNINGS_KEY = "tender_business_warnings"

_REASON_SUFFIX = "Please update the field highlighted in red manually."

_CATALOG_PROFILE_CODES = frozenset(
    {
        BusinessError.MISSING_QTY_PER_UNIT.value,
        BusinessError.MISSING_TOTAL_QTY.value,
        BusinessError.MISSING_UNIT_DIMS.value,
    }
)


def get_tender_business_warnings(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized ``{code, message, context?}`` rows from workflow state."""
    raw = data.get(TENDER_BUSINESS_WARNINGS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        if not code and not message:
            continue
        row: dict[str, Any] = {"code": code, "message": message}
        context = warning_context(item)
        if context:
            row["context"] = context
        out.append(row)
    return out


def _catalog_profile_dedupe_key(
    code: str,
    context: dict[str, str],
) -> tuple[str, str] | None:
    if code not in _CATALOG_PROFILE_CODES:
        return None
    pack_code = str(context.get("pack_code") or "").strip()
    if not pack_code:
        return None
    return (code, pack_code)


def _collapse_duplicate_catalog_profile_warnings(
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep one row per catalog profile gap (same code + pack_code on shared row)."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for warning in warnings:
        code = warning_code(warning)
        context = warning_context(warning)
        key = _catalog_profile_dedupe_key(code, context)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
            pack_code = context.get("pack_code", "")
            warning = {
                **warning,
                "context": {"pack_code": pack_code} if pack_code else {},
            }
        out.append(warning)
    return out


def append_tender_business_warning(
    data: dict[str, Any],
    *,
    code: str,
    message: str,
    context: dict[str, str] | None = None,
) -> None:
    """Append one business-gap warning to ``state.data``."""
    warnings = data.setdefault(TENDER_BUSINESS_WARNINGS_KEY, [])
    if not isinstance(warnings, list):
        warnings = []
        data[TENDER_BUSINESS_WARNINGS_KEY] = warnings

    normalized_context = dict(context) if context else {}
    if is_suppressed_by_warnings(
        get_tender_business_warnings(data),
        code=code,
        context=normalized_context or None,
    ):
        return

    row: dict[str, Any] = {"code": code, "message": message}
    if normalized_context:
        row["context"] = normalized_context

    if any(
        isinstance(item, dict)
        and str(item.get("code") or "").strip() == code
        and str(item.get("message") or "").strip() == message
        and warning_context(item) == normalized_context
        for item in warnings
    ):
        return

    catalog_key = _catalog_profile_dedupe_key(code, normalized_context)
    if catalog_key is not None and any(
        _catalog_profile_dedupe_key(warning_code(item), warning_context(item))
        == catalog_key
        for item in warnings
    ):
        return

    warnings.append(row)


def filter_primary_business_warnings(
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep root-cause warnings only; drop downstream dependents in the same scope."""
    indexed = list(enumerate(warnings))
    suppress_ids: set[int] = set()

    for i, warning in indexed:
        dependent_code = warning_code(warning)
        if not dependent_code:
            continue
        dependent_context = warning_context(warning)
        for j, ancestor in indexed:
            if i == j:
                continue
            ancestor_code = warning_code(ancestor)
            if not ancestor_code:
                continue
            if is_suppressed_by_ancestor(
                ancestor_code=ancestor_code,
                ancestor_context=warning_context(ancestor),
                dependent_code=dependent_code,
                dependent_context=dependent_context,
            ):
                suppress_ids.add(i)
                break

    return _collapse_duplicate_catalog_profile_warnings(
        [warning for idx, warning in indexed if idx not in suppress_ids]
    )


def format_reason_for_failure_html(warnings: list[dict[str, Any]]) -> str:
    """Vendor email header HTML for root-cause gaps; empty when there are none."""
    seen_messages: set[str] = set()
    messages: list[str] = []
    for warning in filter_primary_business_warnings(warnings):
        message = str(warning.get("message") or "").strip()
        if not message or message in seen_messages:
            continue
        seen_messages.add(message)
        messages.append(message)
    if not messages:
        return ""
    body = "<br />".join(escape(message) for message in messages)
    return (
        '<p style="color: red; font-style: italic; margin-bottom: 12px;">'
        f"{body}<br />{escape(_REASON_SUFFIX)}</p>"
    )
