"""Load delivery location rows from persisted ``data_imports`` (email ingest)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.delivery_locations import rows_from_spreadsheet_sheets
from app.domain.gelita.email_attachments import (
    DELIVERY_LOCATIONS_FILE_NAME,
    DELIVERY_LOCATIONS_SHEET_NAME,
)
from app.models.data_import import DataImportDataType

logger = get_logger(__name__)


def load_delivery_location_rows_from_data_import(tenant_id: str) -> list[dict[str, Any]]:
    """
    Return cleaned Delivery locations sheet rows for a tenant.

    Reads the latest ``data_imports`` row with ``data_type=delivery_location`` and
    ``file_name=delivery_location.xlsx``. Returns an empty list when missing or invalid.
    """
    tid = tenant_id.strip()
    if not tid:
        return []

    def _load(repos: Any) -> tuple[str | None, dict[str, Any] | None]:
        repo = repos.data_imports
        import_id = repo.find_id_by_tenant_data_type_and_file_name(
            tenant_id=tid,
            data_type=DataImportDataType.DELIVERY_LOCATION.value,
            file_name=DELIVERY_LOCATIONS_FILE_NAME,
        )
        if not import_id:
            return None, None
        raw_data = repo.fetch_raw_data_by_id(tenant_id=tid, data_import_id=import_id)
        return import_id, raw_data

    import_id, raw_data = run_with_repos(_load)
    if not import_id:
        logger.info(
            "delivery locations: no data_import for tenant_id=%s file_name=%s",
            tid,
            DELIVERY_LOCATIONS_FILE_NAME,
        )
        return []

    if not raw_data:
        return []

    try:
        ingest = raw_data["ingest"]
        data = ingest["data"]
        spreadsheet = data["spreadsheet"]
    except (KeyError, TypeError):
        logger.warning(
            "delivery locations: invalid raw_data envelope tenant_id=%s import_id=%s",
            tid,
            import_id,
        )
        return []

    if spreadsheet.get("format") != "xlsx":
        return []

    sheets = spreadsheet.get("sheets")
    if not isinstance(sheets, list):
        return []

    rows = rows_from_spreadsheet_sheets(
        sheets,
        preferred_tab_name=DELIVERY_LOCATIONS_SHEET_NAME,
    )
    if not rows:
        sheet_dicts = [s for s in sheets if isinstance(s, dict)]
        available = [
            {
                "name": s.get("name"),
                "row_count": len(s.get("rows") or [])
                if isinstance(s.get("rows"), list)
                else 0,
            }
            for s in sheet_dicts
        ]
        logger.warning(
            "delivery locations: no non-empty sheet in import_id=%s file_name=%s; "
            "sheets=%s",
            import_id,
            DELIVERY_LOCATIONS_FILE_NAME,
            available,
        )
        return []

    logger.info(
        "delivery locations: loaded row_count=%s import_id=%s tenant_id=%s",
        len(rows),
        import_id,
        tid,
    )
    return rows
