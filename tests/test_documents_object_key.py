"""Tests for documents.object_key insert/read."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.models.document import DocumentType
from app.tools import documents as doc_mod


@contextmanager
def _fake_db_scope():
    class _FakeRepos:
        session = object()

    yield _FakeRepos()


@pytest.fixture
def patch_documents_db(monkeypatch):
    fake_row = {
        "id": "id-1",
        "object_key": "freightx/ratecon_attachments/ratecon_SHIP-1.pdf",
        "type": "ratecon",
        "shipment_id": "SHIP-1",
        "created_at": None,
    }
    monkeypatch.setattr(doc_mod, "db_scope", _fake_db_scope)
    monkeypatch.setattr(doc_mod, "_table_name", lambda: "documents")
    monkeypatch.setattr(
        doc_mod,
        "fetchone_dict",
        lambda session, sql, params: fake_row,
    )


def test_read_document_returns_latest_row(patch_documents_db):
    out = doc_mod.read_document("SHIP-1", DocumentType.RATECON)
    assert out["found"] is True
    assert out["id"] == "id-1"
    assert out["object_key"] == "freightx/ratecon_attachments/ratecon_SHIP-1.pdf"
    assert out["shipment_id"] == "SHIP-1"
    assert out["type"] == "ratecon"
