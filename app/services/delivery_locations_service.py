"""Delivery locations lookup: in-memory index from an injected row source.

Production uses rows loaded from the latest email-ingested ``data_imports`` row
(``delivery_location.xlsx``) via :func:`load_delivery_location_rows_from_data_import`.
Callers may inject any ``rows_provider`` (tests use in-memory row lists).
"""

from __future__ import annotations

from typing import Any, Callable

from app.core.logger import get_logger
from app.domain.delivery_locations import DeliveryLocationsIndex
from app.domain.delivery_locations_column_mapping import (
    DeliveryLocationsColumnMapping,
    DeliveryLocationsHeaderMapping,
)

logger = get_logger(__name__)


def _unconfigured_rows_provider() -> list[dict[str, Any]]:
    raise RuntimeError(
        "delivery_locations not configured: pass rows_provider or use "
        "load_delivery_location_rows_from_data_import(tenant_id)"
    )


class DeliveryLocationsService:
    """Build a :class:`DeliveryLocationsIndex` from workbook row dicts.

    Args:
        rows_provider: Callable that returns row dicts (required in production).
        column_mapping: When set, index rows by Excel column letters (positional).
        header_mapping: When set, use named columns when the row has header keys.
    """

    def __init__(
        self,
        *,
        rows_provider: Callable[[], list[dict[str, Any]]] | None = None,
        column_mapping: DeliveryLocationsColumnMapping | None = None,
        header_mapping: DeliveryLocationsHeaderMapping | None = None,
    ) -> None:
        self._rows_provider = rows_provider or _unconfigured_rows_provider
        self._column_mapping = column_mapping
        self._header_mapping = header_mapping
        self._cached_index: DeliveryLocationsIndex | None = None

    def index_for_ingest_run(self) -> DeliveryLocationsIndex | None:
        """Load Delivery locations once for a tender ingest batch.

        Returns ``None`` when rows cannot be loaded (logged; callers
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
        self._cached_index = DeliveryLocationsIndex(
            rows,
            column_mapping=self._column_mapping,
            header_mapping=self._header_mapping,
        )
        return self._cached_index

    def lookup(self, delivery_number: str) -> dict[str, Any] | None:
        """Return one cleaned row dict for ``delviery``, or ``None`` if not found."""
        index = self.build_index()
        return index.lookup(delivery_number)
