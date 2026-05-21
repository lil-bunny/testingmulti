"""Persist spreadsheet-projected tender rows into ``tenders``."""

from __future__ import annotations

from typing import Any, Optional

from app.core.logger import get_logger
from app.domain.delivery_address import resolve_delivery_address
from app.domain.load_tendering_tender_rows import projected_row_to_tender_insert
from app.integrations.pgeocode import lookup_state
from app.repositories.tenders_repository import TendersRepository
from app.services.activity_log_service import ActivityLogService
from app.services.delivery_locations_service import DeliveryLocationsService

logger = get_logger(__name__)


class TendersIngestService:
    def __init__(
        self,
        repository: Optional[TendersRepository] = None,
        delivery_locations: Optional[DeliveryLocationsService] = None,
    ) -> None:
        self._repository = repository or TendersRepository()
        self._delivery_locations = delivery_locations or DeliveryLocationsService()

    def persist_from_projected_rows(
        self,
        *,
        tenant_id: str,
        data_import_id: str | None,
        projected_rows: list[dict[str, Any]],
    ) -> list[str | None]:
        """
        Insert tender rows for valid projected rows.

        Returns one entry per ``projected_rows`` index: ``tenders.id`` when inserted, else ``None``.
        """
        tid = tenant_id.strip()
        did = (data_import_id or "").strip()
        if not tid or not did or not projected_rows:
            return []

        locations_index = self._delivery_locations.index_for_ingest_run()

        out: list[str | None] = [None] * len(projected_rows)
        batch: list[dict[str, Any]] = []
        batch_row_indices: list[int] = []
        skipped = 0

        for row_index, row in enumerate(projected_rows):
            mapped = projected_row_to_tender_insert(row)
            if mapped is None:
                skipped += 1
                continue
            mapped["delivery_address"] = resolve_delivery_address(
                row.get("delivery_address_code"),
                locations_index,
                state_resolver=lookup_state,
            )
            batch.append(
                {
                    **mapped,
                    "tenant_id": tid,
                    "data_import_id": did,
                }
            )
            batch_row_indices.append(row_index)

        if skipped:
            logger.warning(
                "tenders ingest: skipped %s unusable projected row(s) data_import_id=%s",
                skipped,
                did,
            )
        if not batch:
            return out

        inserted_ids = self._repository.insert_batch(batch)
        if len(inserted_ids) != len(batch):
            logger.error(
                "tenders ingest: id count mismatch inserted=%s batch=%s data_import_id=%s",
                len(inserted_ids),
                len(batch),
                did,
            )
        activity_log_svc = ActivityLogService()
        batch_by_row_index = dict(zip(batch_row_indices, batch, strict=False))
        for idx, tender_id in zip(batch_row_indices, inserted_ids, strict=False):
            out[idx] = tender_id
            if not tender_id:
                continue
            row = batch_by_row_index.get(idx)
            if not row:
                continue
            order_number = str(row.get("order_number") or "")
            customer_name = str(row.get("customer_name") or "")
            activity_log_svc.record_tender_created_action(
                tenant_id=tid,
                tender_id=tender_id,
                order_number=order_number,
                customer_name=customer_name,
            )
            activity_log_svc.record_tender_processing_status_change(
                tenant_id=tid,
                tender_id=tender_id,
            )

        return out
