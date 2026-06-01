"""Tender reads and writes for load tendering (orchestration over repositories)."""

from __future__ import annotations

from typing import Any, TypedDict

from app.repositories.tender_products_repository import TenderProductsRepository
from app.repositories.tenders_repository import TendersRepository

class TenderOrderPlusProducts(TypedDict):
    tender: dict[str, Any]
    products: list[dict[str, Any]]

class TenderService:
    def __init__(
        self,
        *,
        tenders_repository: TendersRepository | None = None,
        tender_products_repository: TenderProductsRepository | None = None,
    ) -> None:
        self._tenders_repo = tenders_repository or TendersRepository()
        self._products_repo = tender_products_repository or TenderProductsRepository()

    def read_order(
        self, *, tenant_id: str, tender_id: str
    ) -> TenderOrderPlusProducts | None:
        """Return ``{tender, products}`` for an order id, or ``None`` if missing."""
        order = self._tenders_repo.get_by_id(
            tenant_id=tenant_id, tender_id=tender_id
        )
        if not order:
            return None
        products = self._products_repo.list_by_tender_id(
            tenant_id=tenant_id, tender_id=tender_id
        )
        return TenderOrderPlusProducts(tender=order, products=products)

    def find_tender_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        """Return ``{id, order_number}`` for a tenant-scoped tender row, or ``None``."""
        return self._tenders_repo.get_by_order_number(
            tenant_id=tenant_id, order_number=order_number
        )

    def update_load_type(
        self, *, tenant_id: str, tender_id: str, load_type: str
    ) -> bool:
        """Persist ``load_type`` on the tender (``LTL`` / ``FTL`` enum labels)."""
        return self._tenders_repo.update_load_type(
            tenant_id=tenant_id,
            tender_id=tender_id,
            load_type=load_type,
        )
