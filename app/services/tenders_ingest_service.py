"""Persist spreadsheet-projected tender rows into ``tenders``."""

from __future__ import annotations

from typing import Any, Optional

from app.core.logger import get_logger
from app.domain.load_tendering_tender_rows import projected_row_to_tender_insert
from app.repositories.tenders_repository import TendersRepository

logger = get_logger(__name__)


class TendersIngestService:
    def __init__(self, repository: Optional[TendersRepository] = None) -> None:
        self._repository = repository or TendersRepository()

    def persist_from_projected_rows(
        self,
        *,
        tenant_id: str,
        data_import_id: str | None,
        projected_rows: list[dict[str, Any]],
    ) -> int:
        tid = tenant_id.strip()
        did = (data_import_id or "").strip()
        if not tid or not did or not projected_rows:
            return 0

        batch: list[dict[str, Any]] = []
        skipped = 0
        for row in projected_rows:
            mapped = projected_row_to_tender_insert(row)
            if mapped is None:
                skipped += 1
                continue
            batch.append(
                {
                    **mapped,
                    "tenant_id": tid,
                    "data_import_id": did,
                }
            )

        if skipped:
            logger.warning(
                "tenders ingest: skipped %s unusable projected row(s) data_import_id=%s",
                skipped,
                did,
            )
        if not batch:
            return 0

        return self._repository.insert_batch(batch)
