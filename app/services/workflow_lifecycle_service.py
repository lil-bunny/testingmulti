from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.core.service_db import run_with_repos
from app.models.status import StatusSubType, StatusType
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository


@dataclass(frozen=True)
class LifecycleResolution:
    """Result of lifecycle resolution."""

    workflow_lifecycle_id: str
    existed: bool


class WorkflowLifecycleService:
    """Resolve or create workflow lifecycle rows from correlation keys."""

    def __init__(
        self,
        *,
        lifecycles_repository: WorkflowLifecyclesRepository | None = None,
    ) -> None:
        self._lifecycles_repo = lifecycles_repository

    def _repo(self, repos: Any) -> WorkflowLifecyclesRepository:
        return self._lifecycles_repo or repos.workflow_lifecycles

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

    def read_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        tid_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tid_raw) if tid_raw else None
        if not tid or not wn:
            return {"found": False}

        tender_uuid: str | None = None
        if tender_id:
            tender_uuid = self._extract_tender_id({"tender_id": tender_id})

        if self._lifecycles_repo is not None:
            repo = self._lifecycles_repo
            lifecycle_id = repo.find_existing_lifecycle_id_tx(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
                thread_id=self._clean(thread_id),
                shipment_id=self._clean(shipment_id),
            )
            if not lifecycle_id:
                return {"found": False}
            row = repo.read_correlation_by_id(lifecycle_id)
        else:
            def _run(repos: Any) -> dict:
                repo = self._repo(repos)
                lifecycle_id = repo.find_existing_lifecycle_id_tx(
                    tenant_id=tid,
                    workflow_name=wn,
                    tender_id=tender_uuid,
                    thread_id=self._clean(thread_id),
                    shipment_id=self._clean(shipment_id),
                )
                if not lifecycle_id:
                    return {"found": False}
                row = repo.read_correlation_by_id(lifecycle_id)
                if not row:
                    return {"found": False}
                return {
                    "found": True,
                    "lifecycle_id": lifecycle_id,
                    "shipment_id": row.get("shipment_id") or "",
                    "tender_id": row.get("tender_id") or "",
                    "email_thread_id": row.get("email_thread_id") or "",
                    "workflow_name": row.get("workflow_name") or "",
                }

            return run_with_repos(_run)

        if not row:
            return {"found": False}

        return {
            "found": True,
            "lifecycle_id": lifecycle_id,
            "shipment_id": row.get("shipment_id") or "",
            "tender_id": row.get("tender_id") or "",
            "email_thread_id": row.get("email_thread_id") or "",
            "workflow_name": row.get("workflow_name") or "",
        }

    def set_email_thread_id(
        self,
        *,
        lifecycle_id: str,
        thread_id: str,
    ) -> bool:
        lid = self._clean(lifecycle_id)
        thread = self._clean(thread_id)
        if not lid or not thread:
            return False
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.set_email_thread_id_tx(
                lifecycle_id=lid,
                email_thread_id=thread,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).set_email_thread_id_tx(
                lifecycle_id=lid,
                email_thread_id=thread,
            )
        )

    def check_lifecycle_exists(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str | None = None,
        thread_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        tenant_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tenant_raw) if tenant_raw else None
        if not tid or not wn:
            return {"exists": False}

        tender_uuid: str | None = None
        if tender_id:
            tender_uuid = self._extract_tender_id({"tender_id": tender_id})

        def _lookup(repo: WorkflowLifecyclesRepository) -> dict:
            lifecycle_id = repo.find_existing_lifecycle_id_tx(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
                thread_id=self._clean(thread_id),
                shipment_id=self._clean(shipment_id),
            )
            if lifecycle_id:
                return {"exists": True, "lifecycle_id": lifecycle_id}
            return {"exists": False}

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def resolve_or_create_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        payload: dict[str, Any],
    ) -> LifecycleResolution:
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

        tender_id = self._extract_tender_id(payload)
        thread_id = self._extract_thread_id(payload)
        shipment_id = self._extract_shipment_id(payload)

        def _resolve(repo: WorkflowLifecyclesRepository) -> LifecycleResolution:
            lifecycle_id, existed = repo.resolve_or_create(
                tenant_id=db_tenant_id,
                workflow_name=workflow_name_clean,
                tender_id=tender_id,
                thread_id=thread_id,
                shipment_id=shipment_id,
            )
            return LifecycleResolution(
                workflow_lifecycle_id=lifecycle_id,
                existed=existed,
            )

        if self._lifecycles_repo is not None:
            return _resolve(self._lifecycles_repo)
        return run_with_repos(lambda repos: _resolve(self._repo(repos)))

    def read_lifecycle_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        lid = self._clean(lifecycle_id)
        if not lid:
            return None
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.read_row_by_id(lid)
        return run_with_repos(lambda repos: self._repo(repos).read_row_by_id(lid))

    def find_lifecycle_row_by_tender_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str,
    ) -> dict[str, Any] | None:
        tid_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tid_raw) if tid_raw else None
        tender_uuid = self._extract_tender_id({"tender_id": tender_id})
        if not tid or not wn or not tender_uuid:
            return None

        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.read_row_by_tender_id(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).read_row_by_tender_id(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
            )
        )

    def update_lifecycle_status(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")
        if status is None and sub_status is None:
            return False
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.update_lifecycle_status_tx(
                lifecycle_id=lid,
                status=status,
                sub_status=sub_status,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).update_lifecycle_status_tx(
                lifecycle_id=lid,
                status=status,
                sub_status=sub_status,
            )
        )

    def update_lifecycle_sub_status(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.update_lifecycle_sub_status_tx(
                lifecycle_id=lid,
                new_sub_status=new_sub_status,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).update_lifecycle_sub_status_tx(
                lifecycle_id=lid,
                new_sub_status=new_sub_status,
            )
        )
