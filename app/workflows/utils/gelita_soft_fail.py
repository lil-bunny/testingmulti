"""Gelita outbound-tender soft-fail helpers for business catalog gaps."""

from __future__ import annotations

from typing import Any

from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.tender_business_warnings import append_tender_business_warning
from app.exceptions import WorkflowException

_MULTI_PRODUCT_CATALOG_GAP_MESSAGES: dict[BusinessError, str] = {
    BusinessError.MISSING_QTY_PER_UNIT: "Quantity per unit is missing.",
    BusinessError.MISSING_TOTAL_QTY: "Total quantity is missing.",
    BusinessError.MISSING_UNIT_DIMS: "Unit dimensions are missing.",
}


def _business_gap_message(
    error: BusinessError,
    *,
    multi_product: bool = False,
    catalog_gap: bool = False,
    **format_kwargs: str,
) -> str:
    if (
        error == BusinessError.MISSING_PACK_CODE
        and not str(format_kwargs.get("pack_code") or "").strip()
    ):
        return "Pack code is missing."
    if (
        catalog_gap
        and multi_product
        and error in _MULTI_PRODUCT_CATALOG_GAP_MESSAGES
    ):
        return _MULTI_PRODUCT_CATALOG_GAP_MESSAGES[error]
    return format_error_message(error, **format_kwargs)


def gelita_tender_created_soft_fail_enabled(state_data: dict[str, Any]) -> bool:
    """True when outbound tender send should warn instead of failing the graph.

    Applies on initial ``tender_created`` and on FTL ``routing_guide_failover``
    (next carrier after reject/timeout), so catalog gaps do not hard-fail the waterfall.
    """
    if str(state_data.get("event_type") or "").strip() == "tender_created":
        return True
    return bool(state_data.get("routing_guide_failover"))


def record_business_gap(
    state_data: dict[str, Any],
    error: BusinessError,
    *,
    multi_product: bool = False,
    catalog_gap: bool = False,
    **format_kwargs: str,
) -> bool:
    """Append a catalog gap when soft-fail applies; return True if recorded."""
    if not gelita_tender_created_soft_fail_enabled(state_data):
        return False
    append_tender_business_warning(
        state_data,
        code=error.value,
        message=_business_gap_message(
            error,
            multi_product=multi_product,
            catalog_gap=catalog_gap,
            **format_kwargs,
        ),
        context=format_kwargs or None,
    )
    return True


def record_business_gap_or_raise(
    state_data: dict[str, Any],
    error: BusinessError,
    *,
    multi_product: bool = False,
    catalog_gap: bool = False,
    **format_kwargs: str,
) -> None:
    """Record the gap when soft-fail applies; otherwise raise ``WorkflowException``."""
    if record_business_gap(
        state_data,
        error,
        multi_product=multi_product,
        catalog_gap=catalog_gap,
        **format_kwargs,
    ):
        return
    raise WorkflowException(
        error,
        _business_gap_message(
            error,
            multi_product=multi_product,
            catalog_gap=catalog_gap,
            **format_kwargs,
        ),
    )
