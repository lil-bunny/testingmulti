"""Tests for documents.object_key insert/read and URL derivation."""

from __future__ import annotations

import pytest

from app.models.document import DocumentType
from app.tools import documents as doc_mod


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return (
            "id-1",
            None,
            "freightx/pod_attachments/ratecon_SHIP-1.pdf",
            "ratecon",
            "SHIP-1",
            None,
        )


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def patch_documents_pg(monkeypatch):
    monkeypatch.setattr(doc_mod, "_ensure_pg_table", lambda: None)
    monkeypatch.setattr(doc_mod, "_try_pg_connection", lambda: _FakeConn())


def test_read_document_derives_url_from_object_key(monkeypatch, patch_documents_pg):
    monkeypatch.setattr(
        doc_mod,
        "public_url_for_object_key",
        lambda key: f"https://example-bucket.test/{key}",
    )
    out = doc_mod.read_document("SHIP-1", DocumentType.RATECON)
    assert out["found"] is True
    assert (
        out["url"]
        == "https://example-bucket.test/freightx/pod_attachments/ratecon_SHIP-1.pdf"
    )
    assert out["id"] == "id-1"
    assert out["shipment_id"] == "SHIP-1"
    assert out["type"] == "ratecon"
