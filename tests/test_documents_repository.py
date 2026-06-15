"""Unit tests for DocumentsRepository (no DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.repositories.documents_repository import DocumentsRepository


def test_find_latest_by_shipment_and_type_delegates_to_fetchone_dict():
    session = MagicMock()
    repo = DocumentsRepository(session)
    fake_row = {
        "id": "1",
        "storage_key": "k",
        "type": "ratecon",
        "shipment_id": "S",
        "metadata": {},
        "created_at": None,
    }
    with patch(
        "app.repositories.documents_repository.fetchone_dict",
        return_value=fake_row,
    ) as fetch:
        out = repo.find_latest_by_shipment_and_type(shipment_id="S", doc_type="ratecon")
    assert out == fake_row
    assert fetch.call_args[0][0] is session
    params = fetch.call_args[0][2]
    assert params == {"shipment_id": "S", "type": "ratecon"}
    assert "metadata" in fetch.call_args[0][1]


def test_upsert_by_storage_key_uses_cast_not_shorthand_uuid():
    session = MagicMock()
    repo = DocumentsRepository(session)
    fake_row = {
        "id": "1",
        "storage_key": "k",
        "type": "ratecon",
        "shipment_id": "S",
        "metadata": {},
        "created_at": None,
    }
    with patch(
        "app.repositories.documents_repository.fetchone_dict",
        return_value=fake_row,
    ) as fetch:
        out = repo.upsert_by_storage_key(
            id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            doc_type="ratecon",
            shipment_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            storage_key="ratecon_attachments/ratecon_1.pdf",
        )
    assert out == fake_row
    sql = fetch.call_args[0][1]
    assert "CAST(:id AS uuid)" in sql
    assert ":id::uuid" not in sql


def test_upsert_pod_by_shipment_includes_metadata_and_conflict_target():
    session = MagicMock()
    repo = DocumentsRepository(session)
    fake_row = {
        "id": "1",
        "storage_key": "k",
        "type": "pod",
        "shipment_id": "S",
        "metadata": {"source_object_keys": ["a"]},
        "created_at": None,
    }
    with patch(
        "app.repositories.documents_repository.fetchone_dict",
        return_value=fake_row,
    ) as fetch:
        out = repo.upsert_pod_by_shipment(
            id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            shipment_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            storage_key="pod_attachments/pod_1.pdf",
            metadata={"source_object_keys": ["a"]},
        )
    assert out == fake_row
    sql = fetch.call_args[0][1]
    assert "ON CONFLICT (shipment_id)" in sql
    assert "type = 'pod'::document_type AND shipment_id IS NOT NULL" in sql
    assert "metadata" in sql
