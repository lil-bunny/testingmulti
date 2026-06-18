"""Workflow error catalog: business, integration, and system error codes."""

from __future__ import annotations

from enum import Enum


class ErrorCategory(str, Enum):
    BUSINESS = "business"
    INTEGRATION = "integration"
    SYSTEM = "system"


class _CatalogError(Enum):
    """Wire code via ``.value``; human text via ``.description``."""

    def __new__(cls, *values: str | tuple[str, str]):
        if len(values) == 1 and isinstance(values[0], tuple):
            code, description = values[0]
        elif len(values) == 2:
            code, description = values
        elif len(values) == 1 and isinstance(values[0], str):
            code, description = values[0], ""
        else:
            raise TypeError(f"Invalid catalog error values: {values!r}")

        obj = object.__new__(cls)
        obj._value_ = code
        obj.description = description
        return obj

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _CatalogError):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)

    def __str__(self) -> str:
        return self.value

    @property
    def category(self) -> ErrorCategory:
        return self.__class__.CATEGORY


class BusinessError(_CatalogError):
    """Domain or data rule violations — input or tenant state is invalid."""

    CATEGORY = ErrorCategory.BUSINESS

    MISSING_TENANT_ID = ("missing_tenant_id", "Tenant ID is missing.")
    MISSING_TENDER_ID = ("missing_tender_id", "Tender ID is missing.")
    TENDER_NOT_FOUND = ("tender_not_found", "Tender not found.")
    MISSING_PRODUCT_LINES = ("missing_product_lines", "No tender products found.")
    MISSING_PACK_CODE = (
        "missing_pack_code",
        "Product pack code {pack_code} is missing.",
    )
    MISSING_DELIVERY_ADDRESS = (
        "missing_delivery_address",
        "Delivery address is not found for delivery location code {del_code}.",
    )
    MISSING_CUSTOMER_NAME = (
        "missing_customer_name",
        "Customer name is not found from delivery location code {del_code}.",
    )
    MISSING_QTY_PER_UNIT = (
        "missing_qty_per_unit",
        "Pack code {pack_code} quantity per unit is missing.",
    )
    MISSING_TOTAL_QTY = (
        "missing_total_qty",
        "Pack code {pack_code} total quantity is missing.",
    )
    MISSING_UNIT_DIMS = (
        "missing_unit_dims",
        "Pack code {pack_code} unit dimensions are missing.",
    )
    MISSING_CUSTOMER_PO = ("missing_customer_po", "Customer PO number is required.")
    # POD lifecycle
    POD_ATTACHMENT_UPLOAD_FAILED = (
        "pod_attachment_upload_failed",
        "POD attachment normalization did not produce a merged PDF.",
    )
    POD_EXTRACTION_EMPTY = (
        "pod_extraction_empty",
        "POD LLM extraction returned no usable data.",
    )
    RATECON_EXTRACTION_EMPTY = (
        "ratecon_extraction_empty",
        "Ratecon LLM extraction returned no usable data.",
    )
    MISSING_PICKUP_ADDRESS = ("missing_pickup_address", "Pickup address is required.")
    MISSING_DELIVERY_DATE = ("missing_delivery_date", "Delivery date is required.")
    INTERNATIONAL_DELIVERY_SKIPPED = (
        "international_delivery_skipped",
        "International (overseas) shipments are skipped",
    )


class IntegrationError(_CatalogError):
    """Failures from external systems (vendor APIs, email providers, etc.)."""

    CATEGORY = ErrorCategory.INTEGRATION

    VENDOR_API_TIMEOUT = ("vendor_api_timeout", "API request timed out.")
    VENDOR_API_ERROR = ("vendor_api_error", "API request failed.")
    EMAIL_SEND_FAILED = ("email_send_failed", "Failed to send email.")
    # POD lifecycle
    POD_S3_DOWNLOAD_FAILED = (
        "pod_s3_download_failed",
        "PDF download failed during POD or Ratecon PDF fetch.",
    )
    TMS_POD_UPLOAD_FAILED = (
        "tms_pod_upload_failed",
        "Turvo POD upload failed.",
    )


class SystemError(_CatalogError):
    """Internal configuration or infrastructure failures."""

    CATEGORY = ErrorCategory.SYSTEM

    MISSING_TENANT_SETTINGS_PALLET_PROFILES = (
        "missing_tenant_settings_pallet_profiles",
        "Pallet Profiles is missing from config.",
    )
    MISSING_TENANT_SETTINGS_DOMESTIC_DELIVERY = (
        "missing_tenant_settings_domestic_delivery",
        "Tenant setting 'domestic_delivery' is required.",
    )
    UNKNOWN_PACK_CODE_PALLET_TYPE = (
        "unknown_pack_code_pallet_type",
        "Pallet type {pallet_type} is missing in pack code {pack_code}.",
    )
    MISSING_TENANT_SETTINGS_GELITA_PICKUP_ADDRESS = (
        "missing_tenant_settings_gelita_pickup_address",
        "Tenant setting 'gelita_pickup_address' is required.",
    )
    UNEXPECTED_NODE_FAILURE = (
        "unexpected_node_failure",
        "An unexpected error occurred while running the workflow.",
    )
    # POD lifecycle
    MISSING_SHIPMENT_ID = (
        "missing_shipment_id",
        "Shipment ID could not be resolved.",
    )


ErrorCode = BusinessError | IntegrationError | SystemError

_ERROR_BY_CODE: dict[str, ErrorCode] = {
    member.value: member
    for cls in (BusinessError, IntegrationError, SystemError)
    for member in cls
}


def resolve_error_code(code: str) -> ErrorCode | None:
    """Map a persisted wire code back to its catalog entry."""
    return _ERROR_BY_CODE.get(code)


def format_error_message(error: _CatalogError, **values: str) -> str:
    """Format a catalog description; missing keys become empty strings."""

    class _SafeFormatMap(dict[str, str]):
        def __missing__(self, key: str) -> str:
            return ""

    return error.description.format_map(_SafeFormatMap(values))


def error_description(code: ErrorCode | str) -> str | None:
    """Return the catalog description for a code or wire string."""
    if isinstance(code, _CatalogError):
        return code.description
    resolved = resolve_error_code(code)
    return resolved.description if resolved else None


def error_category(code: ErrorCode | str) -> ErrorCategory:
    """Return the catalog category for a code or wire string."""
    if isinstance(code, _CatalogError):
        return code.category
    resolved = resolve_error_code(str(code))
    return resolved.category if resolved else ErrorCategory.SYSTEM


def workflow_error_payload(
    *,
    code: str,
    message: str,
    category: ErrorCategory | None = None,
) -> dict[str, str]:
    """Build the ``state.data['error']`` payload."""
    resolved_category = category or error_category(code)
    return {
        "category": resolved_category.value,
        "code": code,
        "message": message,
    }


def has_workflow_error(state_data: dict) -> bool:
    """True when ``state.data`` contains a workflow error payload."""
    error = state_data.get("error")
    return isinstance(error, dict) and bool(error.get("code"))
