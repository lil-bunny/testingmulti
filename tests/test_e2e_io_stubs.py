"""Unit tests for opt-in POD E2E I/O stubs (test layer only)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from tests.e2e import e2e_io_stubs
from tests.e2e.celery_worker_stubs import install_pod_e2e_stubs


@pytest.fixture(autouse=True)
def _reset_stub_install():
    import importlib

    import tests.e2e.celery_worker_stubs as bootstrap

    bootstrap._INSTALLED = False
    e2e_io_stubs.clear_e2e_s3_store()
    yield
    bootstrap._INSTALLED = False
    e2e_io_stubs.clear_e2e_s3_store()
    importlib.reload(importlib.import_module("app.tools.email"))
    importlib.reload(importlib.import_module("app.services.s3bucket_service"))
    try:
        importlib.reload(importlib.import_module("app.workflows.nodes.email"))
    except ImportError:
        pass


def test_read_attachment_bytes_uses_fixture_map(monkeypatch, tmp_path):
    f1 = tmp_path / "one.pdf"
    f1.write_bytes(b"%PDF-1.4 one")
    monkeypatch.setenv("POD_E2E_STUB_ATTACHMENTS", "1")
    monkeypatch.setenv(
        "POD_E2E_ATTACHMENT_FIXTURES",
        json.dumps({"att-1": str(f1)}),
    )
    assert e2e_io_stubs.read_attachment_bytes("att-1") == b"%PDF-1.4 one"


def test_read_attachment_bytes_default_path_missing_raises(monkeypatch):
    monkeypatch.setenv("POD_E2E_STUB_ATTACHMENTS", "1")
    monkeypatch.delenv("POD_E2E_ATTACHMENT_FIXTURES", raising=False)
    monkeypatch.delenv("POD_E2E_ATTACHMENT_FIXTURE_PATH", raising=False)
    with patch.object(e2e_io_stubs, "_default_fixture_path") as mock_default:
        mock_default.return_value = e2e_io_stubs._repo_root() / "missing.pdf"
        with pytest.raises(FileNotFoundError):
            e2e_io_stubs.read_attachment_bytes("att-x")


def test_s3_upload_download_round_trip():
    up = e2e_io_stubs.s3_upload_stub(
        file_content=b"pod-bytes",
        filename="pod_test.pdf",
        folder="pod_attachments",
    )
    assert up["success"] is True
    key = up["object_key"]
    assert key == "pod_attachments/pod_test.pdf"

    down = e2e_io_stubs.s3_download_stub(key)
    assert down["success"] is True
    assert down["body"] == b"pod-bytes"


def test_install_stubs_patches_get_email_attachments(monkeypatch, tmp_path):
    fixture = tmp_path / "pod.pdf"
    fixture.write_bytes(b"%PDF-1.4 stubbed")
    monkeypatch.setenv("POD_E2E_STUB_ATTACHMENTS", "1")
    monkeypatch.setenv("POD_E2E_ATTACHMENT_FIXTURE_PATH", str(fixture))

    install_pod_e2e_stubs()

    from app.tools.email import get_email_attachments

    result = get_email_attachments("email-1", "any-att-id", "acct-1")
    assert result == b"%PDF-1.4 stubbed"


def test_install_stubs_leaves_unipile_when_env_off(monkeypatch):
    monkeypatch.delenv("POD_E2E_STUB_ATTACHMENTS", raising=False)
    monkeypatch.delenv("POD_E2E_STUB_S3", raising=False)

    install_pod_e2e_stubs()

    from app.tools.email import get_email_attachments

    with patch("app.tools.email.Unipile") as mock_cls:
        mock_cls.return_value.get_email_attachment.return_value = b"live"
        result = get_email_attachments("e1", "a1", "acc")
    assert result == b"live"


def test_install_stubs_patches_s3_bucket(monkeypatch):
    monkeypatch.setenv("POD_E2E_STUB_S3", "1")
    install_pod_e2e_stubs()

    from app.services.s3bucket_service import S3Bucket

    bucket = S3Bucket(s3_client=MagicMock(), bucket_name="ignored")
    up = bucket.upload_file(
        file_content=b"x",
        filename="f.pdf",
        content_type="application/pdf",
    )
    assert up["success"] is True
    down = bucket.download_object_bytes(up["object_key"])
    assert down["success"] is True
    assert down["body"] == b"x"
    bucket.s3_client.put_object.assert_not_called()
