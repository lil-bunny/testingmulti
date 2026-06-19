"""Unit tests for business error dependency graph and scoped suppression."""

from __future__ import annotations

from app.domain.business_error_dependencies import (
    is_suppressed_by_ancestor,
    is_suppressed_by_warnings,
    scopes_match,
)
from app.domain.error_catalog import BusinessError


def test_scopes_match_requires_same_del_code() -> None:
    assert scopes_match(
        ancestor_code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
        ancestor_context={"del_code": "44120611"},
        dependent_code=BusinessError.MISSING_CUSTOMER_NAME.value,
        dependent_context={"del_code": "44120611"},
    )
    assert not scopes_match(
        ancestor_code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
        ancestor_context={"del_code": "44120611"},
        dependent_code=BusinessError.MISSING_CUSTOMER_NAME.value,
        dependent_context={"del_code": "41000100"},
    )


def test_scopes_match_requires_same_pack_code() -> None:
    assert scopes_match(
        ancestor_code=BusinessError.MISSING_PACK_CODE.value,
        ancestor_context={"pack_code": "5326"},
        dependent_code=BusinessError.MISSING_QTY_PER_UNIT.value,
        dependent_context={"pack_code": "5326"},
    )
    assert not scopes_match(
        ancestor_code=BusinessError.MISSING_PACK_CODE.value,
        ancestor_context={"pack_code": "5326"},
        dependent_code=BusinessError.MISSING_QTY_PER_UNIT.value,
        dependent_context={"pack_code": "9999"},
    )


def test_is_suppressed_by_ancestor_delivery_customer_chain() -> None:
    assert is_suppressed_by_ancestor(
        ancestor_code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
        ancestor_context={"del_code": "44120611"},
        dependent_code=BusinessError.MISSING_CUSTOMER_NAME.value,
        dependent_context={"del_code": "44120611"},
    )
    assert not is_suppressed_by_ancestor(
        ancestor_code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
        ancestor_context={"del_code": "44120611"},
        dependent_code=BusinessError.MISSING_PACK_CODE.value,
        dependent_context={"pack_code": "5326"},
    )


def test_is_suppressed_by_warnings_uses_existing_rows() -> None:
    warnings = [
        {
            "code": BusinessError.MISSING_DELIVERY_ADDRESS.value,
            "message": "addr",
            "context": {"del_code": "44120611"},
        }
    ]
    assert is_suppressed_by_warnings(
        warnings,
        code=BusinessError.MISSING_CUSTOMER_NAME.value,
        context={"del_code": "44120611"},
    )
    assert not is_suppressed_by_warnings(
        warnings,
        code=BusinessError.MISSING_CUSTOMER_NAME.value,
        context={"del_code": "41000100"},
    )
