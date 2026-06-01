"""Load delivery location rows from persisted ``data_imports`` (email ingest)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.delivery_locations import (
    clean_delivery_locations_sheet,
    select_delivery_locations_sheet,
)
from app.domain.delivery_locations_import import (
    DELIVERY_LOCATIONS_FILE_NAME,
    DELIVERY_LOCATIONS_SHEET_NAME,
)
from app.models.data_import import DataImportDataType
from app.repositories.data_imports_repository import DataImportsRepository

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

    repo = DataImportsRepository()
    import_id = repo.find_id_by_tenant_data_type_and_file_name(
        tenant_id=tid,
        data_type=DataImportDataType.DELIVERY_LOCATION.value,
        file_name=DELIVERY_LOCATIONS_FILE_NAME,
    )
    if not import_id:
        logger.info(
            "delivery locations: no data_import for tenant_id=%s file_name=%s",
            tid,
            DELIVERY_LOCATIONS_FILE_NAME,
        )
        return []

    raw_data = repo.fetch_raw_data_by_id(tenant_id=tid, data_import_id=import_id)
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

    sheet_dicts = [s for s in sheets if isinstance(s, dict)]
    selected = select_delivery_locations_sheet(
        sheet_dicts,
        preferred_tab_name=DELIVERY_LOCATIONS_SHEET_NAME,
    )
    if selected is None:
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

    cleaned = clean_delivery_locations_sheet(selected)
    rows = cleaned.get("rows") or []
    logger.info(
        "delivery locations: using sheet name=%r row_count=%s import_id=%s",
        selected.get("name"),
        len(rows),
        import_id,
    )
    return [r for r in rows if isinstance(r, dict)]
