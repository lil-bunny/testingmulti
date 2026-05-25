"""Post-process email-driven spreadsheet imports: read projections and persist tender rows."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.core.logger import get_logger
from app.services.data_imports_read_service import DataImportsReadService
from app.services.delivery_locations_service import DeliveryLocationsService
from app.services.tenders_ingest_service import TendersIngestService

logger = get_logger(__name__)


def load_email_data_import_projection(
    *,
    tenant_id: str,
    data_import_id: str | None,
    projection: Mapping[str, Sequence[str]],
) -> list[dict[str, Any]]:
    """
    Fetch and project tabular rows for an email-ingested ``data_imports`` row.

    On failure or missing prerequisites, logs and returns an empty list.
    """
    tid = tenant_id.strip()
    did = (data_import_id or "").strip()
    if not tid or not did:
        return []
    try:
        read_svc = DataImportsReadService()
        projected, _meta = read_svc.get_projected_rows(
            tenant_id=tid,
            data_import_id=did,
            projection=projection,
        )
    except Exception:
        logger.exception(
            "email import projection: read failed tenant_id=%s data_import_id=%s",
            tid,
            did,
        )
        return []
    if projected is None:
        logger.warning(
            "email import projection: data_import_id present but no DB row tenant_id=%s id=%s",
            tid,
            did,
        )
        return []
    return projected


def persist_tender_rows_from_email_import_projection(
    *,
    tenant_id: str,
    data_import_id: str | None,
    projected_rows: list[dict[str, Any]],
    delivery_locations: DeliveryLocationsService | None = None,
) -> list[str | None]:
    """
    Insert tender rows derived from projected spreadsheet data.

    Returns one ``tenders.id`` (or ``None``) per projected row index. On failure, logs and
    returns an empty list.
    """
    try:
        ingest_service = TendersIngestService(
            delivery_locations=delivery_locations or DeliveryLocationsService(),
        )
        return ingest_service.persist_from_projected_rows(
            tenant_id=tenant_id,
            data_import_id=data_import_id,
            projected_rows=projected_rows,
        )
    except Exception:
        logger.exception(
            "email import projection: tender persist failed tenant_id=%s data_import_id=%s",
            tenant_id,
            data_import_id,
        )
        return []
