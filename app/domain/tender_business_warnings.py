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

TENDER_BUSINESS_WARNINGS_KEY = "tender_business_warnings"

_REASON_SUFFIX = "Please update the field highlighted in red manually."


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

    return [warning for idx, warning in indexed if idx not in suppress_ids]


def format_reason_for_failure_html(warnings: list[dict[str, Any]]) -> str:
    """Vendor email header HTML for root-cause gaps; empty when there are none."""
    messages = [
        str(w.get("message") or "").strip()
        for w in filter_primary_business_warnings(warnings)
    ]
    messages = [m for m in messages if m]
    if not messages:
        return ""
    body = "<br />".join(escape(message) for message in messages)
    return (
        '<p style="color: red; font-style: italic; margin-bottom: 12px;">'
        f"{body}<br />{escape(_REASON_SUFFIX)}</p>"
    )
