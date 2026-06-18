"""Collect Gelita business catalog gaps on the tender_created path without failing the graph."""

from __future__ import annotations

from html import escape
from typing import Any

TENDER_BUSINESS_WARNINGS_KEY = "tender_business_warnings"


def get_tender_business_warnings(data: dict[str, Any]) -> list[dict[str, str]]:
    """Return normalized ``{code, message}`` rows from workflow state."""
    raw = data.get(TENDER_BUSINESS_WARNINGS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        message = str(item.get("message") or "").strip()
        if code or message:
            out.append({"code": code, "message": message})
    return out


def append_tender_business_warning(
    data: dict[str, Any],
    *,
    code: str,
    message: str,
) -> None:
    """Append one business-gap warning to ``state.data``."""
    warnings = data.setdefault(TENDER_BUSINESS_WARNINGS_KEY, [])
    if not isinstance(warnings, list):
        warnings = []
        data[TENDER_BUSINESS_WARNINGS_KEY] = warnings
    warnings.append({"code": code, "message": message})


def format_reason_for_failure_html(warnings: list[dict[str, str]]) -> str:
    """Vendor email footer HTML for collected gaps; empty when there are none."""
    messages = [str(w.get("message") or "").strip() for w in warnings]
    messages = [m for m in messages if m]
    if not messages:
        return ""
    body = "<br />".join(escape(message) for message in messages)
    return (
        '<p style="color: red; font-style: italic; margin-top: 12px; margin-bottom: 0;">'
        f"{body}</p>"
    )
