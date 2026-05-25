"""
Email gateway webhook — optional attachment fetch, ingest, and data_imports (e.g. Unipile).

Keeps HTTP routes thin as more attachment kinds (pdf, images, ...) are added.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.core.logger import get_logger
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.services import ingest_service
from app.services.data_imports_service import DataImportsService
from app.services.unipile_service import UnipileException
from app.services.workflow_classifier_service import (
    build_unipile_attachment_fetch_context,
    email_first_attachment,
    extract_email_attachment_metadata,
)
from app.tools.email import get_email_attachments

logger = get_logger(__name__)


def infer_email_attachment_ingest_kind(
    attachment: dict[str, Any], file_name: str | None, mime_type: str | None
) -> str | None:
    """
    Map email gateway attachment metadata to an ingest/parser kind.

    Extend as parsers are wired; return None when unsupported or deliberately skipped.
    """
    ext = str(attachment.get("extension") or "").strip().lower().lstrip(".")
    name = (file_name or str(attachment.get("name") or "")).strip().lower()
    mt = (mime_type or "").strip().lower()

    if ext == "xlsx" or name.endswith(".xlsx") or "spreadsheetml" in mt:
        return "excel"

    # Documents
    # if ext == "pdf" or name.endswith(".pdf") or "application/pdf" in mt:
    #     return "pdf"
    #
    # if ext == "csv" or name.endswith(".csv") or mt == "text/csv":
    #     return "csv"

    # Images (POD scans, screenshots, ...)
    # if ext in {"png", "jpg", "jpeg", "webp", "gif", "tif", "tiff"} or mt.startswith(
    #     "image/"
    # ):
    #     return "image"

    return None


def _attachment_fetch_ctx_complete(ctx: dict[str, Any]) -> bool:
    return bool(
        ctx.get("email_id") and ctx.get("account_id") and ctx.get("attachment_id")
    )


async def _fetch_and_record_excel_attachment(
    *,
    workflow_name: str,
    data_import_tenant_id: str,
    ingest_source_type: DataImportSourceType,
    data_import_data_type: DataImportDataType,
    fetch_ctx: dict[str, Any],
    file_name: str | None,
    mime_type: str | None,
) -> Optional[str]:
    try:
        file_bytes = await asyncio.to_thread(
            get_email_attachments,
            fetch_ctx["email_id"],
            fetch_ctx["attachment_id"],
            fetch_ctx["account_id"],
        )
    except UnipileException:
        logger.exception(
            "unipile: get_email_attachment failed workflow_name=%s email_id=%s attachment_id=%s",
            workflow_name,
            fetch_ctx.get("email_id"),
            fetch_ctx.get("attachment_id"),
        )
        return None

    ingest_result = ingest_service.ingest_data(
        source_type=ingest_source_type.value,
        tenant_id=data_import_tenant_id,
        file_name=file_name,
        data_type=data_import_data_type.value,
        mime_type=mime_type,
        data=file_bytes,
        parse_spreadsheet=True,
    )
    return DataImportsService().record_email_load_tendering_import(
        tenant_id=data_import_tenant_id,
        source_type=ingest_source_type,
        file_name=file_name,
        mime_type=mime_type,
        ingest_result=ingest_result,
    )


async def process_email_webhook_attachment_import(
    *,
    payload: dict[str, Any],
    workflow_name: str,
    data_import_tenant_id: str,
    data_import_data_type: DataImportDataType = DataImportDataType.LOAD_TENDER,
    ingest_source_type: DataImportSourceType = DataImportSourceType.EMAIL,
) -> Optional[str]:
    """If the payload has an ingestible attachment, fetch bytes and persist import rows.

    Returns the ``data_imports.id`` (text UUID) when a row was inserted, else ``None``.

    ``data_import_data_type`` is stored as ``data_imports.data_type`` (via ingest).

    ``ingest_source_type`` is stored as ingest + DB ``source_type``. Future API imports
    can pass ``DataImportSourceType.API``.
    """
    tid = data_import_tenant_id.strip()
    if not tid:
        raise ValueError("data_import_tenant_id is required")

    attachment = email_first_attachment(payload)
    if attachment is None:
        return None

    fetch_ctx = build_unipile_attachment_fetch_context(payload, attachment)
    if not _attachment_fetch_ctx_complete(fetch_ctx):
        logger.info(
            "unipile webhook: attachment present but incomplete fetch context workflow_name=%s; skipping ingest",
            workflow_name,
        )
        return None

    meta = extract_email_attachment_metadata(attachment)
    file_name = ((meta.get("name") if meta else None) or "").strip() or None
    mime_type = ((meta.get("mime") if meta else None) or "").strip() or None
    ingest_kind = infer_email_attachment_ingest_kind(attachment, file_name, mime_type)

    if ingest_kind == "excel":
        return await _fetch_and_record_excel_attachment(
            workflow_name=workflow_name,
            data_import_tenant_id=tid,
            ingest_source_type=ingest_source_type,
            data_import_data_type=data_import_data_type,
            fetch_ctx=fetch_ctx,
            file_name=file_name,
            mime_type=mime_type,
        )

    # elif ingest_kind == "pdf":
    #     await _fetch_and_record_pdf_attachment(...)
    #     return

    logger.info(
        "unipile webhook: skipping attachment ingest workflow_name=%s file_name=%s ingest_kind=%s",
        workflow_name,
        file_name,
        ingest_kind,
    )
    return None
