"""Monkeypatch Unipile fetch + S3 I/O for POD mail-free E2E (test layer only)."""

from __future__ import annotations

import importlib
from typing import Any

from celery.signals import worker_process_init

from tests.e2e import e2e_io_stubs

_INSTALLED = False


def install_pod_e2e_stubs() -> None:
    """Patch production call sites when ``POD_E2E_STUB_*`` env vars are set."""
    global _INSTALLED
    if _INSTALLED:
        return
    if not e2e_io_stubs.e2e_stub_attachments_enabled() and not e2e_io_stubs.e2e_stub_s3_enabled():
        return

    if e2e_io_stubs.e2e_stub_attachments_enabled():

        def _stub_get_email_attachments(
            email_id: str, attachment_id: str, account_id: str
        ) -> bytes:
            return e2e_io_stubs.read_attachment_bytes(str(attachment_id or ""))

        email_tools = importlib.import_module("app.tools.email")
        email_tools.get_email_attachments = _stub_get_email_attachments

        def _stub_fetch_with_retry(*, email_id, attachment_id, account_id, **kwargs):
            return e2e_io_stubs.read_attachment_bytes(str(attachment_id or ""))

        for mod_name in (
            "app.services.email_webhook_attachment_ingestion",
            "app.tools.ratecon",
            "app.services.ratecon_document_service",
            "app.services.pod_lifecycle.attachment_pipeline_service",
        ):
            try:
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "get_email_attachments"):
                    mod.get_email_attachments = _stub_get_email_attachments
                if hasattr(mod, "fetch_email_attachment_bytes_with_retry"):
                    mod.fetch_email_attachment_bytes_with_retry = _stub_fetch_with_retry
            except ImportError:
                pass

    if e2e_io_stubs.e2e_stub_s3_enabled():
        from app.core.config import settings as app_settings

        s3_mod = importlib.import_module("app.services.s3bucket_service")
        bucket_cls = s3_mod.S3Bucket

        def _stub_upload(
            self: Any,
            file_content: bytes,
            filename: str,
            content_type: str,
            folder: str = app_settings.BUCKET_POD_ATTACHMENTS_FOLDER,
        ) -> dict[str, Any]:
            return e2e_io_stubs.s3_upload_stub(
                file_content=file_content,
                filename=filename,
                folder=folder,
            )

        def _stub_download(self: Any, object_key: str) -> dict[str, Any]:
            return e2e_io_stubs.s3_download_stub(object_key)

        bucket_cls.upload_file = _stub_upload  # type: ignore[method-assign]
        bucket_cls.download_object_bytes = _stub_download  # type: ignore[method-assign]

    _INSTALLED = True


@worker_process_init.connect
def _install_stubs_on_worker_process(**_kwargs: Any) -> None:
    install_pod_e2e_stubs()
