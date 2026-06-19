"""Ingest lookup keys kept in metadata when catalog resolution fails."""

from __future__ import annotations

from typing import Any

from app.domain.delivery_address import CUSTOMER_NAME_SOURCE_UNKNOWN
from app.domain.delivery_locations import normalize_delivery_number
from app.domain.spreadsheet_cells import identifier_string_from_cell

SOURCE_KEY = "source"


def _source_dict(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    raw = metadata.get(SOURCE_KEY)
    return raw if isinstance(raw, dict) else {}


def _normalized_pack_code_text(row: dict[str, Any]) -> str:
    return str(row.get("pack_code") or "").strip()


def _normalized_delivery_code_text(row: dict[str, Any]) -> str:
    raw = row.get("delivery_address_code")
    if raw is None:
        return ""
    normalized = normalize_delivery_number(raw)
    if normalized:
        return normalized
    return identifier_string_from_cell(raw) or ""


def product_metadata_for_ingest(
    row: dict[str, Any],
    *,
    pack_code_id: str | None,
) -> dict[str, Any]:
    text = _normalized_pack_code_text(row)
    if pack_code_id or not text:
        return {}
    return {SOURCE_KEY: {"pack_code": text}}


def tender_metadata_source_patch(
    row: dict[str, Any],
    *,
    delivery_address: dict[str, Any] | None,
    customer_name_source: str | None,
) -> dict[str, Any]:
    code = _normalized_delivery_code_text(row)
    if not code:
        return {}
    if delivery_address is not None and customer_name_source != CUSTOMER_NAME_SOURCE_UNKNOWN:
        return {}
    return {SOURCE_KEY: {"delivery_address_code": code}}


def merge_metadata(base: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base) if isinstance(base, dict) else {}
    if not patch:
        return out
    for key, value in patch.items():
        if key == SOURCE_KEY and isinstance(value, dict):
            existing = out.get(SOURCE_KEY)
            merged_source = dict(existing) if isinstance(existing, dict) else {}
            merged_source.update(value)
            out[SOURCE_KEY] = merged_source
        else:
            out[key] = value
    return out


def source_pack_code(product: dict[str, Any]) -> str:
    direct = str(product.get("source_pack_code") or "").strip()
    if direct:
        return direct
    return str(_source_dict(product.get("metadata")).get("pack_code") or "").strip()


def source_delivery_address_code(tender: dict[str, Any]) -> str:
    source = str(
        _source_dict(tender.get("metadata")).get("delivery_address_code") or ""
    ).strip()
    if source:
        return source
    return str(tender.get("delivery_address_code") or "").strip()


def pack_code_for_product_gap(product: dict[str, Any]) -> str:
    catalog = str(product.get("pack_code") or "").strip()
    if catalog:
        return catalog
    return source_pack_code(product)


def product_gap_context(
    product: dict[str, Any],
    *,
    pack_code: str | None = None,
) -> dict[str, str]:
    context: dict[str, str] = {}
    product_id = str(product.get("id") or "").strip()
    if product_id:
        context["tender_product_id"] = product_id
    code = (pack_code if pack_code is not None else pack_code_for_product_gap(product)).strip()
    if code:
        context["pack_code"] = code
    return context


def catalog_profile_gap_context(
    product: dict[str, Any],
    *,
    pack_code: str | None = None,
) -> dict[str, str]:
    """Order-level scope when ``pack_code_id`` resolved but catalog profile is incomplete."""
    code = (pack_code if pack_code is not None else pack_code_for_product_gap(product)).strip()
    return {"pack_code": code} if code else {}


def product_or_catalog_gap_context(
    product: dict[str, Any],
    *,
    pack_code: str | None = None,
) -> tuple[dict[str, str], bool]:
    """Return warning context and whether the gap is on the shared catalog row."""
    if product.get("pack_code_id"):
        return catalog_profile_gap_context(product, pack_code=pack_code), True
    return product_gap_context(product, pack_code=pack_code), False


def delivery_gap_context(tender: dict[str, Any], state_data: dict[str, Any]) -> dict[str, str]:
    from app.domain.load_tendering_state import ingest_delivery_address_code

    code = source_delivery_address_code(tender) or ingest_delivery_address_code(state_data)
    return {"del_code": code} if code else {}
