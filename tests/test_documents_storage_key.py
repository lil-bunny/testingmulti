"""Tests for documents.storage_key insert/read."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.models.document import DocumentType
from app.tools import documents as doc_mod

_SHIPMENTS_ROW_ID = "e76d2aee-1234-5678-9abc-def012345678"


@pytest.fixture
def patch_documents_db(monkeypatch):
    fake_row = {
        "id": "id-1",
        "storage_key": "freightx/ratecon_attachments/ratecon_SHIP-1.pdf",
        "type": "ratecon",
        "shipment_id": _SHIPMENTS_ROW_ID,
        "created_at": None,
    }
    fake_documents = MagicMock()
    fake_documents.find_latest_by_shipment_and_type.return_value = fake_row

    class _FakeRepos:
        session = object()
        documents = fake_documents

    fake_repos = _FakeRepos()

    @contextmanager
    def _fake_db_scope():
        yield fake_repos

    monkeypatch.setattr(doc_mod, "db_scope", _fake_db_scope)


def test_read_document_returns_latest_row(patch_documents_db):
    out = doc_mod.read_document(_SHIPMENTS_ROW_ID, DocumentType.RATECON)
    assert out["found"] is True
    assert out["id"] == "id-1"
    assert out["storage_key"] == "freightx/ratecon_attachments/ratecon_SHIP-1.pdf"
    assert out["shipment_id"] == _SHIPMENTS_ROW_ID
    assert out["type"] == "ratecon"
