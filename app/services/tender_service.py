"""Tender reads and writes for load tendering (orchestration over repositories)."""

from __future__ import annotations

from typing import Any, TypedDict, TYPE_CHECKING

from app.core.logger import get_logger
from app.core.service_db import run_with_repos

if TYPE_CHECKING:
    from app.repositories.tender_products_repository import TenderProductsRepository
    from app.repositories.tenders_repository import TendersRepository

logger = get_logger(__name__)


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

    def update_carrier_name(
        self,
        *,
        tenant_id: str,
        tender_id: str,
        carrier_name: str | None,
    ) -> bool:
        """Write denormalized routing-guide carrier name on the tender row."""
        if self._tenders_repo is not None:
            return self._tenders_repo.update_carrier_name(
                tenant_id=tenant_id,
                tender_id=tender_id,
                carrier_name=carrier_name,
            )
        return run_with_repos(
            lambda repos: repos.tenders.update_carrier_name(
                tenant_id=tenant_id,
                tender_id=tender_id,
                carrier_name=carrier_name,
            )
        )

    def assign_carrier_from_routing_guide(self, state: Any) -> bool:
        """
        After outbound tender mail, persist the routing-guide plan carrier on the tender row.

        FTL only — reads ``routing_guide_attempt`` from lifecycle metadata and resolves plan A/B/C
        via ``resolve_carrier_for_tender``. Invoked from ``record_tender_sent_to_carrier`` node.
        """
        from app.domain.gelita.routing_guide_lifecycle import routing_guide_attempt_from_state
        from app.domain.load_tendering_settings import is_ftl_load_type, resolve_load_type
        from app.domain.load_tendering_state import get_tender
        from app.tools.routing_guide_carrier import resolve_carrier_for_tender

        if not is_ftl_load_type(resolve_load_type(state)):
            return False

        data = getattr(state, "data", None) or {}
        tenant_id = str(
            getattr(state, "tenant_id", None) or data.get("tenant_id") or ""
        ).strip()
        tender_id = str(data.get("tender_id") or "").strip()
        if not tenant_id or not tender_id:
            logger.warning(
                "assign_carrier_from_routing_guide skipped missing tenant_id or tender_id"
            )
            return False

        tender = dict(get_tender(data) or {})
        attempt = routing_guide_attempt_from_state(data)
        tenant_slug = str(
            getattr(state, "tenant_slug", None) or data.get("tenant_slug") or ""
        ).strip() or None

        resolution = resolve_carrier_for_tender(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            tender=tender,
            attempt=attempt,
        )
        # Lane miss or missing carrier email → explicit NULL (not inbound From address).
        if resolution.lane_miss or resolution.missing_carrier_email:
            carrier_name = None
        else:
            name = str(resolution.plan_carrier_name or "").strip()
            carrier_name = name or None

        updated = self.update_carrier_name(
            tenant_id=tenant_id,
            tender_id=tender_id,
            carrier_name=carrier_name,
        )
        if not updated:
            logger.warning(
                "assign_carrier_from_routing_guide failed tender_id=%s attempt=%s",
                tender_id,
                attempt,
            )
        return updated
