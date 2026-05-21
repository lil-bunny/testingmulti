"""Tests for delivery_address enrichment during tender ingest."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.delivery_locations import DeliveryLocationsIndex
from app.services.delivery_locations_service import DeliveryLocationsService
from app.services.tenders_ingest_service import TendersIngestService


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


@patch("app.services.tenders_ingest_service.ActivityLogService")
def test_ingest_attaches_delivery_address_from_projected_code(
    _mock_activity_cls: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.tenders_ingest_service.lookup_state",
        lambda _country, _postal: "IA",
    )

    repo = MagicMock()
    tender_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    repo.insert_batch.return_value = [tender_uuid]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = _locations_index()

    svc = TendersIngestService(repository=repo, delivery_locations=locations)
    rows = [
        {
            "order_number": "N1",
            "customer_match": "C",
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


@patch("app.services.tenders_ingest_service.ActivityLogService")
def test_ingest_delivery_address_state_falls_back_to_empty_when_lookup_returns_none(
    _mock_activity_cls: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.tenders_ingest_service.lookup_state",
        lambda _country, _postal: None,
    )

    repo = MagicMock()
    repo.insert_batch.return_value = ["eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = _locations_index()

    svc = TendersIngestService(repository=repo, delivery_locations=locations)
    rows = [
        {
            "order_number": "N3",
            "customer_match": "C",
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


@patch("app.services.tenders_ingest_service.ActivityLogService")
def test_ingest_delivery_address_null_when_index_unavailable(
    _mock_activity_cls: MagicMock,
) -> None:
    repo = MagicMock()
    repo.insert_batch.return_value = ["dddddddd-dddd-dddd-dddd-dddddddddddd"]

    locations = MagicMock(spec=DeliveryLocationsService)
    locations.index_for_ingest_run.return_value = None

    svc = TendersIngestService(repository=repo, delivery_locations=locations)
    rows = [
        {
            "order_number": "N2",
            "customer_match": "C",
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
