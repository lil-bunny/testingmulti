"""Tests for delivery_address enrichment during tender ingest."""

from __future__ import annotations

from unittest.mock import MagicMock


from app.domain.delivery_locations import DeliveryLocationsIndex
from app.repositories.tenders_repository import TenderInsertResult
from app.services.delivery_locations_service import DeliveryLocationsService
from app.services.tenders_ingest_service import TendersIngestService
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _locations_index() -> DeliveryLocationsIndex:
    return DeliveryLocationsIndex(
        [
            {
                "delviery": "41000100",
                "Name": "CARRIER CLAIMS ABF FREIGHT",
                "Street": "1420 STEUBEN STREET",
                "Zip Code": "51105",
                "City": "SIOUX CITY",
                "country name": "U.S.A.",
            }
        ]
    )


def _ingest_svc_with_products(repo: MagicMock) -> TendersIngestService:
    products = MagicMock()
    products.existing_line_keys.return_value = set()
    pack_codes = MagicMock()
    pack_codes.active_pack_code_id_index.return_value = {}
    return TendersIngestService(
        repository=repo,
        tender_products_repository=products,
        pack_codes_repository=pack_codes,
    )


def test_ingest_attaches_delivery_address_from_projected_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.tenders_ingest_service.lookup_state",
        lambda _country, _postal: "IA",
    )

    repo = MagicMock()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [
        TenderInsertResult(tender_id=tender_uuid, created=True),
    ]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = _locations_index()

    svc = _ingest_svc_with_products(repo)
    svc._delivery_locations = locations
    rows = [
        {
            "order_number": "N1",
            "order_position": 1,
            "weight_unit": "KG",
            "product_name": "P",
            "order_quantity": 2,
            "delivery_address_code": "41000100",
        },
    ]
    ids = svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    assert ids == [tender_uuid]
    batch = repo.insert_batch.call_args[0][0]
    assert batch[0]["delivery_address"]["city"] == "SIOUX CITY"
    assert batch[0]["delivery_address"]["postal_code"] == "51105"
    assert batch[0]["delivery_address"]["state"] == "IA"
    assert batch[0]["metadata"]["source"] == {"delivery_address_code": "41000100"}
    assert batch[0]["metadata"]["customer_name_source"] == "unknown"


def test_ingest_delivery_address_state_falls_back_to_empty_when_lookup_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.tenders_ingest_service.lookup_state",
        lambda _country, _postal: None,
    )

    repo = MagicMock()
    repo.insert_batch.return_value = [
        TenderInsertResult(
            tender_id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            created=True,
        ),
    ]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = _locations_index()

    svc = _ingest_svc_with_products(repo)
    svc._delivery_locations = locations
    rows = [
        {
            "order_number": "N3",
            "order_position": 1,
            "weight_unit": "KG",
            "product_name": "P",
            "order_quantity": 1,
            "delivery_address_code": "41000100",
        },
    ]
    svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    batch = repo.insert_batch.call_args[0][0]
    assert batch[0]["delivery_address"]["state"] == ""


def test_ingest_delivery_address_null_when_index_unavailable() -> None:
    repo = MagicMock()
    repo.insert_batch.return_value = [
        TenderInsertResult(
            tender_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            created=True,
        ),
    ]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = None

    svc = _ingest_svc_with_products(repo)
    svc._delivery_locations = locations
    rows = [
        {
            "order_number": "N2",
            "order_position": 1,
            "weight_unit": "KG",
            "product_name": "P",
            "order_quantity": 1,
            "delivery_address_code": "41000100",
        },
    ]
    svc.persist_from_projected_rows(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_import_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        projected_rows=rows,
    )
    batch = repo.insert_batch.call_args[0][0]
    assert batch[0]["delivery_address"] is None
    assert batch[0]["metadata"]["source"] == {"delivery_address_code": "41000100"}
