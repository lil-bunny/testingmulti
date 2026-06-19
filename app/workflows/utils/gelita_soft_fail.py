"""Gelita ``tender_created`` soft-fail helpers for business catalog gaps."""

from __future__ import annotations

from typing import Any

from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.tender_business_warnings import append_tender_business_warning
from app.exceptions import WorkflowException


def gelita_tender_created_soft_fail_enabled(state_data: dict[str, Any]) -> bool:
    """True when ``tender_created`` should warn instead of failing the graph."""
    return str(state_data.get("event_type") or "").strip() == "tender_created"


def record_business_gap(
    state_data: dict[str, Any],
    error: BusinessError,
    **format_kwargs: str,
) -> bool:
    """Append a catalog gap when soft-fail applies; return True if recorded."""
    if not gelita_tender_created_soft_fail_enabled(state_data):
        return False
    append_tender_business_warning(
        state_data,
        code=error.value,
        message=format_error_message(error, **format_kwargs),
        context=format_kwargs or None,
    )
    return True


def record_business_gap_or_raise(
    state_data: dict[str, Any],
    error: BusinessError,
    **format_kwargs: str,
) -> None:
    """Record the gap on ``tender_created``; otherwise raise ``WorkflowException``."""
    if record_business_gap(state_data, error, **format_kwargs):
        return
    raise WorkflowException(
        error,
        format_error_message(error, **format_kwargs),
    )
