"""Delivery locations lookup: in-memory index built from the SharePoint sheet.

The workbook is fetched once per :class:`DeliveryLocationsService` instance
(see ``_cached_index``) and never written to disk. Callers pass a
``rows_provider`` built from ``tenants.settings`` (see Gelita inbound email).

Tests pass an in-memory provider to avoid network or disk I/O.
"""

from __future__ import annotations

from typing import Any, Callable

from app.core.logger import get_logger
from app.domain.delivery_locations import (
    DeliveryLocationsIndex,
    clean_delivery_locations_sheet,
    select_delivery_locations_sheet,
)
from app.domain.delivery_locations_column_mapping import DeliveryLocationsColumnMapping
from app.integrations.sharepoint import fetch_sharepoint_xlsx_bytes
from app.utils.excel import xlsx_bytes_to_sheet_records

logger = get_logger(__name__)


def _fetch_delivery_locations_rows_from_sharepoint(
    share_url: str,
    tab_name: str,
    max_rows: int,
) -> list[dict[str, Any]]:
    """Download the workbook from SharePoint and return the cleaned row dicts."""
    xlsx_bytes = fetch_sharepoint_xlsx_bytes(share_url)
    envelope = xlsx_bytes_to_sheet_records(
        xlsx_bytes, max_rows_per_sheet=max_rows
    )
    sheet_list = [
        s for s in (envelope.get("sheets") or []) if isinstance(s, dict)
    ]
    selected = select_delivery_locations_sheet(
        sheet_list,
        preferred_tab_name=tab_name,
    )
    if selected is None:
        available = [
            {
                "name": s.get("name"),
                "row_count": len(s.get("rows") or [])
                if isinstance(s.get("rows"), list)
                else 0,
            }
            for s in sheet_list
        ]
        raise RuntimeError(
            f"No non-empty delivery locations sheet in workbook. "
            f"preferred_tab={tab_name!r} available={available}"
        )
    cleaned = clean_delivery_locations_sheet(selected)
    rows = cleaned.get("rows") or []
    return [r for r in rows if isinstance(r, dict)]


def _unconfigured_rows_provider() -> list[dict[str, Any]]:
    raise RuntimeError(
        "delivery_locations not configured: pass rows_provider from tenant_settings"
    )


class DeliveryLocationsService:
    """Build a :class:`DeliveryLocationsIndex` from the SharePoint workbook.

    Args:
        rows_provider: Callable that returns row dicts. Required for production
            (built from ``load_tendering.delivery_locations_excel`` in tenant settings).
        column_mapping: When set, index rows by Excel column letters (positional only).
    """

    def __init__(
        self,
        *,
        rows_provider: Callable[[], list[dict[str, Any]]] | None = None,
        column_mapping: DeliveryLocationsColumnMapping | None = None,
    ) -> None:
        self._rows_provider = rows_provider or _unconfigured_rows_provider
        self._column_mapping = column_mapping
        self._cached_index: DeliveryLocationsIndex | None = None

    def index_for_ingest_run(self) -> DeliveryLocationsIndex | None:
        """Load Delivery locations once for a tender ingest batch.

        Returns ``None`` when the workbook cannot be read (logged; callers
        should fall back to ``delivery_address = null``).
        """
        try:
            return self.build_index()
        except Exception as exc:
            logger.exception(
                "delivery locations: failed to load index for ingest "
                "(delivery_address will be null)"
            )
            return None

    def build_index(self) -> DeliveryLocationsIndex:
        if self._cached_index is not None:
            return self._cached_index
        rows = self._rows_provider()
        self._cached_index = DeliveryLocationsIndex(
            rows, column_mapping=self._column_mapping
        )
        return self._cached_index

    def lookup(self, delivery_number: str) -> dict[str, Any] | None:
        """Return one cleaned row dict for ``delviery``, or ``None`` if not found."""
        index = self.build_index()
        return index.lookup(delivery_number)
