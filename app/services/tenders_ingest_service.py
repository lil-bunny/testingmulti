"""Persist spreadsheet-projected tender rows into ``tenders``."""

from __future__ import annotations

from typing import Any, Optional

from app.core.logger import get_logger
from app.domain.delivery_address import resolve_delivery_address
from app.domain.load_tendering_tender_rows import projected_row_to_tender_insert
from app.integrations.pgeocode import lookup_state
from app.repositories.pack_codes_repository import PackCodesRepository
from app.repositories.tenders_repository import TendersRepository
from app.services.delivery_locations_service import DeliveryLocationsService

logger = get_logger(__name__)


class TendersIngestService:
    def __init__(
        self,
        repository: Optional[TendersRepository] = None,
        delivery_locations: Optional[DeliveryLocationsService] = None,
        pack_codes_repository: Optional[PackCodesRepository] = None,
    ) -> None:
        self._repository = repository or TendersRepository()
        self._delivery_locations = delivery_locations or DeliveryLocationsService()
        self._pack_codes = pack_codes_repository or PackCodesRepository()

    def persist_from_projected_rows(
        self,
        *,
        tenant_id: str,
        data_import_id: str | None,
        projected_rows: list[dict[str, Any]],
    ) -> list[str | None]:
        """
        Insert tender rows for valid projected rows.

        Returns one entry per ``projected_rows`` index: ``tenders.id`` when the order was
        **newly** inserted (workflow should run); ``None`` when the order already existed
        or the row was unusable (workflow should not run).
        """
        tid = tenant_id.strip()
        did = (data_import_id or "").strip()
        if not tid or not did or not projected_rows:
            return []

        locations_index = self._delivery_locations.index_for_ingest_run()
        pack_code_index = self._pack_codes.active_pack_code_id_index(tenant_id=tid)

        out: list[str | None] = [None] * len(projected_rows)
        row_slots: list[tuple[int, dict[str, Any]]] = []
        skipped = 0

        for row_index, row in enumerate(projected_rows):
            mapped = projected_row_to_tender_insert(
                row,
                active_pack_code_index=pack_code_index,
            )
            if mapped is None:
                skipped += 1
                continue
            mapped["delivery_address"] = resolve_delivery_address(
                row.get("delivery_address_code"),
                locations_index,
                state_resolver=lookup_state,
            )
            row_slots.append(
                (
                    row_index,
                    {
                        **mapped,
                        "tenant_id": tid,
                        "data_import_id": did,
                    },
                )
            )

        if skipped:
            logger.warning(
                "tenders ingest: skipped %s unusable projected row(s) data_import_id=%s",
                skipped,
                did,
            )
        if not row_slots:
            return out

        # One tender per (tenant_id, order_number): first spreadsheet row wins.
        insert_batch: list[dict[str, Any]] = []
        seen_order_numbers: set[str] = set()
        duplicate_row_count = 0
        for _row_index, mapped in row_slots:
            order_number = str(mapped.get("order_number") or "").strip()
            if not order_number:
                continue
            if order_number in seen_order_numbers:
                duplicate_row_count += 1
                continue
            seen_order_numbers.add(order_number)
            insert_batch.append(mapped)

        if duplicate_row_count:
            logger.info(
                "tenders ingest: %s duplicate order_number row(s) in import; "
                "reusing first row per order data_import_id=%s",
                duplicate_row_count,
                did,
            )

        if not insert_batch:
            return out

        insert_results = self._repository.insert_batch(insert_batch)
        if len(insert_results) != len(insert_batch):
            logger.error(
                "tenders ingest: id count mismatch inserted=%s batch=%s data_import_id=%s",
                len(insert_results),
                len(insert_batch),
                did,
            )
            return out

        order_to_tender_id: dict[str, str] = {}
        order_created: dict[str, bool] = {}
        skipped_existing = 0
        for row, result in zip(insert_batch, insert_results, strict=True):
            order_number = str(row["order_number"])
            order_to_tender_id[order_number] = result.tender_id
            order_created[order_number] = result.created
            if not result.created:
                skipped_existing += 1

        if skipped_existing:
            logger.info(
                "tenders ingest: %s order(s) already in tenders; skipping workflow enqueue "
                "data_import_id=%s",
                skipped_existing,
                did,
            )

        for row_index, mapped in row_slots:
            order_number = str(mapped.get("order_number") or "").strip()
            if order_number and order_created.get(order_number):
                out[row_index] = order_to_tender_id.get(order_number)

        return out
