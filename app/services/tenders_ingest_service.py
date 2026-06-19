"""Persist spreadsheet-projected tender rows into ``tenders`` and ``tender_products``."""

from __future__ import annotations

from typing import Any, Optional

from app.core.service_db import run_with_repos
from app.core.logger import get_logger
from app.domain.delivery_address import (
    CUSTOMER_NAME_SOURCE_UNKNOWN,
    resolve_customer_name,
    resolve_delivery_address,
)
from app.domain.load_tendering_tender_rows import (
    dedupe_projected_rows_by_order_and_position,
    projected_row_to_tender_insert,
    projected_row_to_tender_product_insert,
    tender_product_line_key,
)
from app.integrations.pgeocode import lookup_state
from app.repositories.pack_codes_repository import PackCodesRepository
from app.repositories.tender_products_repository import TenderProductsRepository
from app.repositories.tenders_repository import TendersRepository
from app.services.delivery_locations_service import DeliveryLocationsService

logger = get_logger(__name__)


class TendersIngestService:
    def __init__(
        self,
        repository: Optional[TendersRepository] = None,
        tender_products_repository: Optional[TenderProductsRepository] = None,
        delivery_locations: Optional[DeliveryLocationsService] = None,
        pack_codes_repository: Optional[PackCodesRepository] = None,
    ) -> None:
        self._repository = repository
        self._tender_products = tender_products_repository
        self._delivery_locations = delivery_locations or DeliveryLocationsService()
        self._pack_codes = pack_codes_repository

    def persist_from_projected_rows(
        self,
        *,
        tenant_id: str,
        data_import_id: str | None,
        projected_rows: list[dict[str, Any]],
    ) -> list[str | None]:
        """
        Insert one ``tenders`` row per distinct order number and attach product lines.

        Returns one entry per ``projected_rows`` index: tender id when insert succeeded
        (caller should enqueue workflow); ``None`` for unusable rows or duplicate
        order positions within the same import.
        """
        tid = tenant_id.strip()
        did = (data_import_id or "").strip()
        if not tid or not did or not projected_rows:
            return []

        locations_index = self._delivery_locations.index_for_ingest_run()

        def _pack_index(repos: Any) -> dict[str, str]:
            repo = self._pack_codes or repos.pack_codes
            return repo.active_pack_code_id_index(tenant_id=tid)

        if self._pack_codes is not None:
            pack_code_index = self._pack_codes.active_pack_code_id_index(tenant_id=tid)
        else:
            pack_code_index = run_with_repos(_pack_index)

        out: list[str | None] = [None] * len(projected_rows)
        kept = dedupe_projected_rows_by_order_and_position(projected_rows)

        row_slots: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        skipped_invalid = 0

        for row_index, row in kept:
            resolved_customer_name, customer_name_source = resolve_customer_name(
                row.get("delivery_address_code"),
                locations_index,
            )
            if customer_name_source == CUSTOMER_NAME_SOURCE_UNKNOWN:
                logger.warning(
                    "tenders ingest: customer_name unresolved from delivery locations "
                    "column J; using placeholder order_number=%r delivery_code=%r "
                    "data_import_id=%s",
                    row.get("order_number"),
                    row.get("delivery_address_code"),
                    did,
                )
            delivery_address = resolve_delivery_address(
                row.get("delivery_address_code"),
                locations_index,
                state_resolver=lookup_state,
            )
            header = projected_row_to_tender_insert(
                row,
                customer_name=resolved_customer_name,
                customer_name_source=customer_name_source,
                delivery_address=delivery_address,
                active_pack_code_index=pack_code_index,
            )
            product = projected_row_to_tender_product_insert(
                row,
                active_pack_code_index=pack_code_index,
            )
            if header is None or product is None:
                skipped_invalid += 1
                continue
            header["delivery_address"] = delivery_address
            row_slots.append(
                (
                    row_index,
                    {
                        **header,
                        "tenant_id": tid,
                        "data_import_id": did,
                    },
                    product,
                )
            )

        skipped_by_dedupe = len(projected_rows) - len(kept)
        if skipped_by_dedupe > 0:
            logger.info(
                "tenders ingest: skipped %s row(s) (invalid order/position or duplicate "
                "order_position) data_import_id=%s",
                skipped_by_dedupe,
                did,
            )
        if skipped_invalid:
            logger.warning(
                "tenders ingest: skipped %s unusable projected row(s) data_import_id=%s",
                skipped_invalid,
                did,
            )
        if not row_slots:
            return out

        insert_batch: list[dict[str, Any]] = []
        seen_order_numbers: set[str] = set()
        duplicate_order_header_count = 0
        for _row_index, header, _product in row_slots:
            order_number = str(header.get("order_number") or "").strip()
            if not order_number:
                continue
            if order_number in seen_order_numbers:
                duplicate_order_header_count += 1
                continue
            seen_order_numbers.add(order_number)
            insert_batch.append(header)

        if duplicate_order_header_count:
            logger.info(
                "tenders ingest: %s duplicate order_number row(s) in import; "
                "reusing first row per order data_import_id=%s",
                duplicate_order_header_count,
                did,
            )

        if not insert_batch:
            return out

        def _persist(
            tenders_repo: TendersRepository,
            products_repo: TenderProductsRepository,
        ) -> list[str | None]:
            insert_results = tenders_repo.insert_batch(insert_batch)
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
            for header, result in zip(insert_batch, insert_results, strict=True):
                order_number = str(header["order_number"])
                order_to_tender_id[order_number] = result.tender_id
                order_created[order_number] = result.created

            existing_by_tender: dict[str, set[tuple]] = {}
            product_batch: list[dict[str, Any]] = []
            for _row_index, header, product in row_slots:
                order_number = str(header["order_number"])
                tender_id = order_to_tender_id.get(order_number)
                if not tender_id:
                    continue
                if tender_id not in existing_by_tender:
                    existing_by_tender[tender_id] = products_repo.existing_line_keys(
                        tender_id=tender_id
                    )
                line_key = tender_product_line_key(product)
                if line_key in existing_by_tender[tender_id]:
                    continue
                existing_by_tender[tender_id].add(line_key)
                product_batch.append(
                    {
                        "tenant_id": tid,
                        "tender_id": tender_id,
                        "pack_code_id": product.get("pack_code_id"),
                        "product_name": product["product_name"],
                        "order_quantity": product["order_quantity"],
                        "price_per_unit": product.get("price_per_unit"),
                        "weight_unit": product.get("weight_unit"),
                        "metadata": product.get("metadata") or {},
                    }
                )

            if product_batch:
                products_repo.insert_batch(product_batch)

            result_out = list(out)
            for row_index, header, _product in row_slots:
                order_number = str(header.get("order_number") or "").strip()
                if order_number and order_created.get(order_number):
                    result_out[row_index] = order_to_tender_id.get(order_number)
            return result_out

        if self._repository is not None and self._tender_products is not None:
            return _persist(self._repository, self._tender_products)
        return run_with_repos(
            lambda repos: _persist(repos.tenders, repos.tender_products)
        )
