"""Human-readable labels for ``StatusType`` / ``StatusSubType`` (activity logs, portal)."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType

# Product vocabulary overrides where machine slugs use "tenant" for the shipper.
_SUB_STATUS_DISPLAY_LABELS: dict[StatusSubType, str] = {
    StatusSubType.TENDER_SENT_TO_TENANT: "Tender Sent To Shipper",
    StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_1: (
        "Tender Sent To Shipper For Carrier 1"
    ),
    StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_2: (
        "Tender Sent To Shipper For Carrier 2"
    ),
    StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_3: (
        "Tender Sent To Shipper For Carrier 3"
    ),
}

# Fallback token swap when a new slug contains "tenant" but no explicit label yet.
_DISPLAY_TOKEN_REPLACEMENTS: dict[str, str] = {
    "tenant": "shipper",
}


def _format_slug(slug: str) -> str:
    return slug.replace("_", " ").title()


def _apply_display_token_replacements(slug: str) -> str:
    for token, replacement in _DISPLAY_TOKEN_REPLACEMENTS.items():
        slug = slug.replace(token, replacement)
    return slug


def label_status(value: StatusType) -> str:
    if value == StatusType.NONE:
        return "None"
    return _format_slug(value.value)


def label_sub_status(value: StatusSubType) -> str:
    if value == StatusSubType.NONE:
        return "None"
    if value in _SUB_STATUS_DISPLAY_LABELS:
        return _SUB_STATUS_DISPLAY_LABELS[value]
    return _format_slug(_apply_display_token_replacements(value.value))
