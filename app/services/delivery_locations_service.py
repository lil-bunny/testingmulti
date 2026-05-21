"""Delivery locations lookup: in-memory index built from the SharePoint sheet.

The workbook is fetched once per :class:`DeliveryLocationsService` instance
(see ``_cached_index``) and never written to disk. Tests can substitute the
SharePoint fetch by passing a ``rows_provider`` callable to the constructor.
"""

from __future__ import annotations

from typing import Any, Callable

from app.configs.gelita_delivery_locations_config import (
    DELIVERY_LOCATIONS_MAX_ROWS,
    DELIVERY_LOCATIONS_SHARE_URL,
    DELIVERY_LOCATIONS_TAB_NAME,
)
from app.core.logger import get_logger
from app.domain.delivery_locations import (
    DeliveryLocationsIndex,
    clean_delivery_locations_sheet,
)
from app.integrations.sharepoint import fetch_sharepoint_xlsx_bytes
from app.utils.excel import xlsx_bytes_to_sheet_records

logger = get_logger(__name__)


def _fetch_delivery_locations_rows_from_sharepoint() -> list[dict[str, Any]]:
    """Download the workbook from SharePoint and return the cleaned row dicts."""
    xlsx_bytes = fetch_sharepoint_xlsx_bytes(DELIVERY_LOCATIONS_SHARE_URL)
    envelope = xlsx_bytes_to_sheet_records(
        xlsx_bytes, max_rows_per_sheet=DELIVERY_LOCATIONS_MAX_ROWS
    )
    for sheet in envelope.get("sheets") or []:
        if sheet.get("name") == DELIVERY_LOCATIONS_TAB_NAME:
            cleaned = clean_delivery_locations_sheet(sheet)
            rows = cleaned.get("rows") or []
            return [r for r in rows if isinstance(r, dict)]
    available = [s.get("name") for s in envelope.get("sheets") or []]
    raise RuntimeError(
        f"Tab {DELIVERY_LOCATIONS_TAB_NAME!r} not found. Available tabs: {available}"
    )


class DeliveryLocationsService:
    """Build a :class:`DeliveryLocationsIndex` from the SharePoint workbook.

    Args:
        rows_provider: Optional callable that returns the row dicts directly.
            When omitted, rows are fetched from the SharePoint share URL in
            :mod:`app.configs.gelita_delivery_locations_config`. Tests pass an
            in-memory provider to avoid any network or disk I/O.
    """

    def __init__(
        self,
        *,
        rows_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._rows_provider = (
            rows_provider or _fetch_delivery_locations_rows_from_sharepoint
        )
        self._cached_index: DeliveryLocationsIndex | None = None

    def index_for_ingest_run(self) -> DeliveryLocationsIndex | None:
        """Load Delivery locations once for a tender ingest batch.

        Returns ``None`` when the workbook cannot be read (logged; callers
        should fall back to ``delivery_address = null``).
        """
        try:
            return self.build_index()
        except Exception:
            logger.exception(
                "delivery locations: failed to load index for ingest "
                "(delivery_address will be null)"
            )
            return None

    def build_index(self) -> DeliveryLocationsIndex:
        if self._cached_index is not None:
            return self._cached_index
        rows = self._rows_provider()
        self._cached_index = DeliveryLocationsIndex(rows)
        return self._cached_index

    def lookup(self, delivery_number: str) -> dict[str, Any] | None:
        """Return one cleaned row dict for ``delviery``, or ``None`` if not found."""
        index = self.build_index()
        return index.lookup(delivery_number)
