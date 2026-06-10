"""
Email gateway webhook — optional attachment fetch, ingest, and data_imports (e.g. Unipile).

Keeps HTTP routes thin as more attachment kinds (pdf, images, ...) are added.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from app.core.logger import get_logger
from app.domain.delivery_locations_import import (
    DELIVERY_LOCATIONS_FILE_NAME,
    unipile_delivery_locations_attachment,
)
from app.domain.load_tendering_import import email_load_tender_xlsx_attachment
from app.domain.ratecon_import import is_pdf_attachment
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.services import ingest_service
from app.services.data_imports_service import DataImportsService
from app.services.unipile_service import UnipileException
from app.domain.unipile_email import (
    build_unipile_attachment_fetch_context,
    extract_email_attachment_metadata,
)
from app.tools.email import get_email_attachments

logger = get_logger(__name__)

_TRANSIENT_UNIPILE_MARKERS = (
    "504",
    "request_timeout",
    "gateway",
    "timeout",
)
_ATTACHMENT_FETCH_ATTEMPTS = 4
_ATTACHMENT_FETCH_BACKOFF_S = (3, 6, 12)


def is_transient_unipile_error(exc: BaseException) -> bool:
    """True when Unipile failure is likely transient (504, gateway, timeout)."""
    if not isinstance(exc, UnipileException):
        return False
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_UNIPILE_MARKERS)


def fetch_email_attachment_bytes_with_retry(
    *,
    email_id: str,
    attachment_id: str,
    account_id: str,
    fetch_fn: Callable[[str, str, str], bytes] | None = None,
) -> bytes:
    """Sync fetch with bounded retries on transient Unipile errors."""
    fn = fetch_fn or get_email_attachments
    last_exc: BaseException | None = None
    for attempt in range(1, _ATTACHMENT_FETCH_ATTEMPTS + 1):
        try:
            return fn(email_id, attachment_id, account_id)
        except UnipileException as exc:
            last_exc = exc
            if attempt >= _ATTACHMENT_FETCH_ATTEMPTS or not is_transient_unipile_error(exc):
                raise
            delay = _ATTACHMENT_FETCH_BACKOFF_S[
                min(attempt - 1, len(_ATTACHMENT_FETCH_BACKOFF_S) - 1)
            ]
            logger.warning(
                "unipile: transient attachment fetch failure attempt=%s/%s email_id=%s "
                "attachment_id=%s retry_in=%ss err=%s",
                attempt,
                _ATTACHMENT_FETCH_ATTEMPTS,
                email_id,
                attachment_id,
                delay,
                exc,
            )
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise UnipileException("attachment fetch failed with no exception")


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

    if is_pdf_attachment(attachment, name or ""):
        return "pdf"

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
    source_email_id: str | None = None,
    source_attachment_id: str | None = None,
) -> str | None:
    try:
        file_bytes = await asyncio.to_thread(
            fetch_email_attachment_bytes_with_retry,
            email_id=fetch_ctx["email_id"],
            attachment_id=fetch_ctx["attachment_id"],
            account_id=fetch_ctx["account_id"],
        )
    except UnipileException:
        logger.exception(
            "unipile: get_email_attachment failed after retries workflow_name=%s "
            "email_id=%s attachment_id=%s",
            workflow_name,
            fetch_ctx.get("email_id"),
            fetch_ctx.get("attachment_id"),
        )
        raise

    spreadsheet_header: int | None = 0
    if data_import_data_type == DataImportDataType.DELIVERY_LOCATION:
        # delivery_location.xlsx is headerless; columns are positional (A, B, J, …).
        spreadsheet_header = None

    ingest_result = ingest_service.ingest_data(
        source_type=ingest_source_type.value,
        tenant_id=data_import_tenant_id,
        file_name=file_name,
        data_type=data_import_data_type.value,
        mime_type=mime_type,
        data=file_bytes,
        parse_spreadsheet=True,
        spreadsheet_header=spreadsheet_header,
    )
    source: dict[str, str] | None = None
    eid = (source_email_id or fetch_ctx.get("email_id") or "").strip()
    aid = (source_attachment_id or fetch_ctx.get("attachment_id") or "").strip()
    if eid and aid:
        source = {"email_id": eid, "attachment_id": aid}

    imports = DataImportsService()
    if data_import_data_type == DataImportDataType.DELIVERY_LOCATION:
        return imports.record_email_delivery_locations_import(
            tenant_id=data_import_tenant_id,
            source_type=ingest_source_type,
            file_name=file_name or DELIVERY_LOCATIONS_FILE_NAME,
            mime_type=mime_type,
            ingest_result=ingest_result,
            source=source,
        )

    return imports.record_email_load_tendering_import(
        tenant_id=data_import_tenant_id,
        source_type=ingest_source_type,
        file_name=file_name,
        mime_type=mime_type,
        ingest_result=ingest_result,
        source=source,
    )


async def process_email_webhook_attachment_import_for_attachment(
    *,
    payload: dict[str, Any],
    attachment: dict[str, Any],
    workflow_name: str,
    data_import_tenant_id: str,
    data_import_data_type: DataImportDataType,
    ingest_source_type: DataImportSourceType = DataImportSourceType.EMAIL,
    skip_fetch_if_existing: bool = True,
) -> str | None:
    """Fetch one attachment and persist to ``data_imports``."""
    tid = data_import_tenant_id.strip()
    if not tid:
        raise ValueError("data_import_tenant_id is required")

    fetch_ctx = build_unipile_attachment_fetch_context(payload, attachment)
    if not _attachment_fetch_ctx_complete(fetch_ctx):
        logger.info(
            "unipile webhook: attachment present but incomplete fetch context "
            "workflow_name=%s; skipping ingest",
            workflow_name,
        )
        return None

    dedupe_types = (DataImportDataType.LOAD_TENDER,)
    if skip_fetch_if_existing and data_import_data_type in dedupe_types:
        existing = DataImportsService().find_by_email_attachment_source(
            tenant_id=tid,
            email_id=fetch_ctx["email_id"],
            attachment_id=fetch_ctx["attachment_id"],
        )
        if existing:
            logger.info(
                "unipile webhook: reusing existing data_import id=%s email_id=%s "
                "attachment_id=%s",
                existing,
                fetch_ctx["email_id"],
                fetch_ctx["attachment_id"],
            )
            return existing

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

    logger.info(
        "unipile webhook: skipping attachment ingest workflow_name=%s file_name=%s "
        "ingest_kind=%s",
        workflow_name,
        file_name,
        ingest_kind,
    )
    return None


async def process_email_webhook_attachment_import(
    *,
    payload: dict[str, Any],
    workflow_name: str,
    data_import_tenant_id: str,
    data_import_data_type: DataImportDataType = DataImportDataType.LOAD_TENDER,
    ingest_source_type: DataImportSourceType = DataImportSourceType.EMAIL,
    skip_fetch_if_existing: bool = True,
    attachment: dict[str, Any] | None = None,
) -> str | None:
    """
    If the payload has an ingestible attachment, fetch bytes and persist import rows.

    When ``attachment`` is omitted, uses the first ``customers_orders_*.xlsx`` attachment.
    """
    tid = data_import_tenant_id.strip()
    if not tid:
        raise ValueError("data_import_tenant_id is required")

    chosen = attachment
    if chosen is None:
        if data_import_data_type == DataImportDataType.DELIVERY_LOCATION:
            chosen = unipile_delivery_locations_attachment(payload)
        else:
            chosen = email_load_tender_xlsx_attachment(payload)

    if chosen is None:
        return None

    return await process_email_webhook_attachment_import_for_attachment(
        payload=payload,
        attachment=chosen,
        workflow_name=workflow_name,
        data_import_tenant_id=tid,
        data_import_data_type=data_import_data_type,
        ingest_source_type=ingest_source_type,
        skip_fetch_if_existing=skip_fetch_if_existing,
    )


async def process_delivery_locations_attachment_import(
    *,
    payload: dict[str, Any],
    workflow_name: str,
    data_import_tenant_id: str,
) -> str | None:
    """Fetch ``delivery_location.xlsx`` and upsert the tenant delivery-locations import."""
    attachment = unipile_delivery_locations_attachment(payload)
    if attachment is None:
        return None

    return await process_email_webhook_attachment_import_for_attachment(
        payload=payload,
        attachment=attachment,
        workflow_name=workflow_name,
        data_import_tenant_id=data_import_tenant_id,
        data_import_data_type=DataImportDataType.DELIVERY_LOCATION,
        ingest_source_type=DataImportSourceType.EMAIL,
        skip_fetch_if_existing=False,
    )
