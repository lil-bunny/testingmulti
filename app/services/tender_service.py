"""Tender reads and writes for load tendering (orchestration over repositories)."""

from __future__ import annotations

from typing import Any, TypedDict

from app.core.service_db import run_with_repos
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
        self._tenders_repo = tenders_repository
        self._products_repo = tender_products_repository

    def read_order(
        self, *, tenant_id: str, tender_id: str
    ) -> TenderOrderPlusProducts | None:
        if self._tenders_repo is not None and self._products_repo is not None:
            order = self._tenders_repo.get_by_id(
                tenant_id=tenant_id, tender_id=tender_id
            )
            if not order:
                return None
            products = self._products_repo.list_by_tender_id(
                tenant_id=tenant_id, tender_id=tender_id
            )
            return TenderOrderPlusProducts(tender=order, products=products)

        def _run(repos: Any) -> TenderOrderPlusProducts | None:
            order = (self._tenders_repo or repos.tenders).get_by_id(
                tenant_id=tenant_id, tender_id=tender_id
            )
            if not order:
                return None
            products = (self._products_repo or repos.tender_products).list_by_tender_id(
                tenant_id=tenant_id, tender_id=tender_id
            )
            return TenderOrderPlusProducts(tender=order, products=products)

        return run_with_repos(_run)

    def find_tender_by_order_number(
        self, *, tenant_id: str, order_number: str
    ) -> dict[str, Any] | None:
        if self._tenders_repo is not None:
            return self._tenders_repo.get_by_order_number(
                tenant_id=tenant_id, order_number=order_number
            )
        return run_with_repos(
            lambda repos: repos.tenders.get_by_order_number(
                tenant_id=tenant_id, order_number=order_number
            )
        )

    def update_load_type(
        self, *, tenant_id: str, tender_id: str, load_type: str
    ) -> bool:
        if self._tenders_repo is not None:
            return self._tenders_repo.update_load_type(
                tenant_id=tenant_id,
                tender_id=tender_id,
                load_type=load_type,
            )
        return run_with_repos(
            lambda repos: repos.tenders.update_load_type(
                tenant_id=tenant_id,
                tender_id=tender_id,
                load_type=load_type,
            )
        )
