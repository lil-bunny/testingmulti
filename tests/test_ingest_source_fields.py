"""Tests for ingest-time source lookup snapshots in metadata."""

from __future__ import annotations

from app.domain.delivery_address import CUSTOMER_NAME_SOURCE_UNKNOWN
from app.domain.ingest_source_fields import (
    delivery_gap_context,
    merge_metadata,
    pack_code_for_product_gap,
    product_gap_context,
    product_metadata_for_ingest,
    product_or_catalog_gap_context,
    source_delivery_address_code,
    source_pack_code,
    tender_metadata_source_patch,
)


def test_product_metadata_for_ingest_unknown_pack_code() -> None:
    row = {"pack_code": "6300"}
    assert product_metadata_for_ingest(row, pack_code_id=None) == {
        "source": {"pack_code": "6300"}
    }


def test_product_metadata_for_ingest_omits_when_resolved() -> None:
    row = {"pack_code": "5326"}
    assert product_metadata_for_ingest(row, pack_code_id="uuid") == {}


def test_product_metadata_for_ingest_omits_blank_sheet_text() -> None:
    assert product_metadata_for_ingest({"pack_code": "  "}, pack_code_id=None) == {}


def test_tender_metadata_source_patch_delivery_address_missing() -> None:
    row = {"delivery_address_code": "44154704"}
    assert tender_metadata_source_patch(
        row,
        delivery_address=None,
        customer_name_source="delivery_location",
    ) == {"source": {"delivery_address_code": "44154704"}}


def test_tender_metadata_source_patch_customer_unresolved() -> None:
    row = {"delivery_address_code": "44120611"}
    assert tender_metadata_source_patch(
        row,
        delivery_address={"city": "Chicago"},
        customer_name_source=CUSTOMER_NAME_SOURCE_UNKNOWN,
    ) == {"source": {"delivery_address_code": "44120611"}}


def test_tender_metadata_source_patch_omits_when_resolved() -> None:
    row = {"delivery_address_code": "44154704"}
    assert (
        tender_metadata_source_patch(
            row,
            delivery_address={"city": "Chicago"},
            customer_name_source="delivery_location",
        )
        == {}
    )


def test_merge_metadata_merges_source_keys() -> None:
    base = {"po_number": "PO1", "source": {"delivery_address_code": "1"}}
    patch = {"source": {"delivery_address_code": "2"}}
    assert merge_metadata(base, patch) == {
        "po_number": "PO1",
        "source": {"delivery_address_code": "2"},
    }


def test_source_pack_code_reads_metadata_and_hydrated_field() -> None:
    assert source_pack_code({"source_pack_code": "6300"}) == "6300"
    assert source_pack_code({"metadata": {"source": {"pack_code": "6300"}}}) == "6300"


def test_source_delivery_address_code_prefers_metadata_source() -> None:
    tender = {
        "delivery_address_code": "enqueue",
        "metadata": {"source": {"delivery_address_code": "44154704"}},
    }
    assert source_delivery_address_code(tender) == "44154704"


def test_pack_code_for_product_gap_prefers_catalog_join() -> None:
    product = {"pack_code": "5326", "metadata": {"source": {"pack_code": "6300"}}}
    assert pack_code_for_product_gap(product) == "5326"


def test_pack_code_for_product_gap_falls_back_to_source() -> None:
    product = {
        "pack_code": "",
        "metadata": {"source": {"pack_code": "6300"}},
    }
    assert pack_code_for_product_gap(product) == "6300"


def test_product_gap_context_includes_scope_keys() -> None:
    context = product_gap_context(
        {
            "id": "prod-1",
            "pack_code": "",
            "metadata": {"source": {"pack_code": "6300"}},
        }
    )
    assert context == {
        "tender_product_id": "prod-1",
        "pack_code": "6300",
    }


def test_product_or_catalog_gap_context_scopes_catalog_row_by_pack_code() -> None:
    product = {
        "id": "prod-1",
        "pack_code_id": "uuid",
        "pack_code": "3002",
    }
    context, catalog_gap = product_or_catalog_gap_context(product)
    assert catalog_gap is True
    assert context == {"pack_code": "3002"}


def test_product_or_catalog_gap_context_keeps_line_scope_when_unresolved() -> None:
    product = {
        "id": "prod-1",
        "pack_code_id": None,
        "metadata": {"source": {"pack_code": "6300"}},
    }
    context, catalog_gap = product_or_catalog_gap_context(product)
    assert catalog_gap is False
    assert context == {"tender_product_id": "prod-1", "pack_code": "6300"}


def test_delivery_gap_context_uses_metadata_source() -> None:
    tender = {"metadata": {"source": {"delivery_address_code": "44120611"}}}
    assert delivery_gap_context(tender, {}) == {"del_code": "44120611"}
