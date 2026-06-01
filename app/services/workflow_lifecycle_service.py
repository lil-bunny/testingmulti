from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.models.status import StatusSubType, StatusType
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository


@dataclass(frozen=True)
class LifecycleResolution:
    """Result of lifecycle resolution."""

    workflow_lifecycle_id: str
    existed: bool


class WorkflowLifecycleService:
    """
    Resolve or create workflow lifecycle rows from correlation keys.

    ``load_id`` is the business order number for load tendering; other workflows
    may pass a vendor load id in ``load_id`` when ``order_number`` is absent.
    """

    def __init__(
        self,
        *,
        lifecycles_repository: WorkflowLifecyclesRepository | None = None,
    ) -> None:
        self._lifecycles_repo = lifecycles_repository or WorkflowLifecyclesRepository()

    @staticmethod
    def _clean(value: Any) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _extract_thread_id(payload: dict[str, Any]) -> Optional[str]:
        return WorkflowLifecycleService._clean(payload.get("thread_id"))

    @staticmethod
    def _extract_shipment_id(payload: dict[str, Any]) -> Optional[str]:
        return WorkflowLifecycleService._clean(payload.get("shipment_id"))

    @staticmethod
    def _extract_tender_id(payload: dict[str, Any]) -> Optional[str]:
        raw = WorkflowLifecycleService._clean(payload.get("tender_id"))
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _extract_load_id(payload: dict[str, Any]) -> Optional[str]:
        from app.domain.load_tendering_state import order_number_from_data

        order = WorkflowLifecycleService._clean(order_number_from_data(payload))
        if order:
            return order
        return WorkflowLifecycleService._clean(payload.get("load_id"))

    def read_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        load_id: str | None = None,
    ) -> dict:
        """Read-only lookup. Returns lifecycle data if found, no row creation."""
        tid_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tid_raw) if tid_raw else None
        if not tid or not wn:
            return {"found": False}

        lifecycle_id = self._lifecycles_repo.find_existing_lifecycle_id_tx(
            tenant_id=tid,
            workflow_name=wn,
            load_id=self._clean(load_id),
            thread_id=self._clean(thread_id),
            shipment_id=self._clean(shipment_id),
        )
        if not lifecycle_id:
            return {"found": False}

        row = self._lifecycles_repo.read_correlation_by_id(lifecycle_id)
        if not row:
            return {"found": False}

        return {
            "found": True,
            "lifecycle_id": lifecycle_id,
            "shipment_id": row.get("shipment_id") or "",
            "load_id": row.get("load_id") or "",
            "email_thread_id": row.get("email_thread_id") or "",
            "workflow_name": row.get("workflow_name") or "",
        }

    def set_email_thread_id(
        self,
        *,
        lifecycle_id: str,
        thread_id: str,
    ) -> bool:
        """Set ``email_thread_id`` on an existing lifecycle row."""
        lid = self._clean(lifecycle_id)
        thread = self._clean(thread_id)
        if not lid or not thread:
            return False
        return self._lifecycles_repo.set_email_thread_id_tx(
            lifecycle_id=lid,
            email_thread_id=thread,
        )

    def check_lifecycle_exists(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str | None = None,
        load_id: str | None = None,
        thread_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        """Check if a lifecycle row exists for given keys."""
        tenant_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tenant_raw) if tenant_raw else None
        if not tid or not wn:
            return {"exists": False}

        tender_uuid: str | None = None
        if tender_id:
            tender_uuid = self._extract_tender_id({"tender_id": tender_id})

        lifecycle_id = self._lifecycles_repo.find_existing_lifecycle_id_tx(
            tenant_id=tid,
            workflow_name=wn,
            load_id=self._clean(load_id),
            tender_id=tender_uuid,
            thread_id=self._clean(thread_id),
            shipment_id=self._clean(shipment_id),
        )
        if lifecycle_id:
            return {"exists": True, "lifecycle_id": lifecycle_id}
        return {"exists": False}

    def resolve_or_create_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        payload: dict[str, Any],
    ) -> LifecycleResolution:
        """
        Resolve existing lifecycle id by correlation keys or create a new row.

        Returns:
            LifecycleResolution(workflow_lifecycle_id=<id>, existed=<bool>)
        """
        tenant_id_clean = self._clean(tenant_id)
        workflow_name_clean = self._clean(workflow_name)
        if not tenant_id_clean or not workflow_name_clean:
            raise ValueError("tenant_id and workflow_name are required")

        db_tenant_id = resolve_graph_tenant_to_uuid(tenant_id_clean)
        if not db_tenant_id:
            raise ValueError(
                f"No matching tenants row for tenant_id={tenant_id_clean!r} "
                "(expected UUID or tenants.slug matching TENANT_CONFIGS key)"
            )

        workflow_lifecycle_id = self._clean(payload.get("workflow_lifecycle_id"))
        if workflow_lifecycle_id:
            try:
                uuid.UUID(workflow_lifecycle_id)
            except (ValueError, AttributeError):
                pass
            else:
                return LifecycleResolution(
                    workflow_lifecycle_id=workflow_lifecycle_id,
                    existed=True,
                )

        load_id = self._extract_load_id(payload)
        tender_id = self._extract_tender_id(payload)
        thread_id = self._extract_thread_id(payload)
        shipment_id = self._extract_shipment_id(payload)

        lifecycle_id, existed = self._lifecycles_repo.resolve_or_create(
            tenant_id=db_tenant_id,
            workflow_name=workflow_name_clean,
            load_id=load_id,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )
        return LifecycleResolution(
            workflow_lifecycle_id=lifecycle_id,
            existed=existed,
        )

    def read_lifecycle_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return tenant_id, workflow_name, status, sub_status, email_thread_id for a lifecycle PK."""
        lid = self._clean(lifecycle_id)
        if not lid:
            return None
        return self._lifecycles_repo.read_row_by_id(lid)

    def update_lifecycle_status(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        """
        Update lifecycle status fields.

        - ``None`` means "leave unchanged".
        - Uses enum types internally.
        - Returns whether any row was updated.
        """
        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")
        if status is None and sub_status is None:
            return False
        return self._lifecycles_repo.update_lifecycle_status_tx(
            lifecycle_id=lid,
            status=status,
            sub_status=sub_status,
        )

    def update_lifecycle_sub_status(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        """Set ``sub_status`` unconditionally. Returns whether a row was updated."""
        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")
        return self._lifecycles_repo.update_lifecycle_sub_status_tx(
            lifecycle_id=lid,
            new_sub_status=new_sub_status,
        )
