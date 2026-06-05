"""Unit tests for DocumentsRepository (no DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.repositories.documents_repository import DocumentsRepository


def test_find_latest_by_shipment_and_type_delegates_to_fetchone_dict():
    session = MagicMock()
    repo = DocumentsRepository(session)
    fake_row = {"id": "1", "object_key": "k", "type": "ratecon", "shipment_id": "S", "created_at": None}
    with patch(
        "app.repositories.documents_repository.fetchone_dict",
        return_value=fake_row,
    ) as fetch:
        out = repo.find_latest_by_shipment_and_type(shipment_id="S", doc_type="ratecon")
    assert out == fake_row
    assert fetch.call_args[0][0] is session
    params = fetch.call_args[0][2]
    assert params == {"shipment_id": "S", "type": "ratecon"}
    assert "documents" in fetch.call_args[0][1]
    assert "ORDER BY created_at DESC" in fetch.call_args[0][1]
