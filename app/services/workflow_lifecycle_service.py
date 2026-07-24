from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from app.core.service_db import run_with_repos
from app.core.logger import get_logger
from app.domain.driver_assignment.reminder_ladder import (
    append_sent_schedule_step,
    sent_schedule_steps_from_metadata,
)
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.shipments_service import ShipmentsService

if TYPE_CHECKING:
    from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
    from app.models.status import StatusSubType, StatusType
    from app.domain.workflow_cancellation import WorkflowCancellationPolicy

logger = get_logger(__name__)


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
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._lifecycles_repo = lifecycles_repository
        self._shipments_service = shipments_service or ShipmentsService()

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
    def _uuid_or_none(value: Any) -> Optional[str]:
        raw = WorkflowLifecycleService._clean(value)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError, TypeError):
            return None

    @staticmethod
    def _extract_db_shipment_id(payload: dict[str, Any]) -> Optional[str]:
        """
        ``workflow_lifecycles.shipment_id`` FK (``shipments.id`` UUID).

        Prefer ``shipments_row_id`` from ratecon upsert; ignore Turvo numeric ``shipment_id``.
        """
        row_id = WorkflowLifecycleService._uuid_or_none(payload.get("shipments_row_id"))
        if row_id:
            return row_id
        return WorkflowLifecycleService._uuid_or_none(payload.get("shipment_id"))

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
    def _shipment_fk_for_lookup(
        workflow_name: str | None,
        shipment_id: str | None,
    ) -> str | None:
        """ratecon / pod_lifecycle: only ``shipments.id`` UUID; others pass through."""
        wn = WorkflowLifecycleService._clean(workflow_name)
        ship = WorkflowLifecycleService._clean(shipment_id)
        if not ship:
            return None
        if wn in ("ratecon", "pod_lifecycle"):
            return WorkflowLifecycleService._uuid_or_none(ship)
        return ship

    def read_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        """Read-only lookup. Returns lifecycle data if found, no row creation.

        Response ``shipment_id`` is ``workflow_lifecycles.shipment_id`` (``shipments.id`` UUID).
        ``shipment_number`` is the external TMS id from ``shipments.shipment_number``.
        """
        tid_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tid_raw) if tid_raw else None
        if not tid or not wn:
            return {"found": False}

        tender_uuid: str | None = None
        if tender_id:
            tender_uuid = self._extract_tender_id({"tender_id": tender_id})

        ship_key = self._shipment_fk_for_lookup(wn, shipment_id)

        if self._lifecycles_repo is not None:
            repo = self._lifecycles_repo
            lifecycle_id = repo.find_existing_lifecycle_id_tx(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
                thread_id=self._clean(thread_id),
                shipment_id=ship_key,
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
                    shipment_id=ship_key,
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
            "workflow_name": row.get("workflow_name") or "",
        }

    def link_shipment_row(
        self,
        *,
        lifecycle_id: str,
        shipments_row_id: str,
    ) -> bool:
        """Set ``workflow_lifecycles.shipment_id`` to ``shipments.id`` when still NULL."""
        lid = self._clean(lifecycle_id)
        sid = self._uuid_or_none(shipments_row_id)
        if not lid or not sid:
            return False
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.update_shipment_id_tx(
                lifecycle_id=lid,
                shipment_id=sid,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).update_shipment_id_tx(
                lifecycle_id=lid,
                shipment_id=sid,
            )
        )

    def resolve_shipments_row_id(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        """
        Resolve ``shipments.id`` from payload.

        Uses ``shipments_row_id``, a UUID ``shipment_id``, or lookup by Turvo
        ``shipment_number`` via ``shipments`` when ``shipment_id`` is external.
        """
        row_id = self._extract_db_shipment_id(payload)
        if row_id:
            return row_id

        external = self._clean(payload.get("shipment_id"))
        if not external:
            return None

        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        if not tid:
            return None

        row = self._shipments_service.get_by_shipment_number(
            tenant_id=tid,
            shipment_number=external,
        )
        if not row:
            return None
        return self._uuid_or_none(row.get("id"))

    def ensure_lifecycle_shipment_linked(
        self,
        *,
        lifecycle_id: str,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        """
        Idempotently link lifecycle FK to ``shipments.id`` when resolvable.

        Returns the internal UUID when found (even if FK was already set).
        """
        row_id = self.resolve_shipments_row_id(
            tenant_id=tenant_id,
            payload=payload,
        )
        if not row_id:
            return None
        self.link_shipment_row(
            lifecycle_id=lifecycle_id,
            shipments_row_id=row_id,
        )
        return row_id

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

        ship_key = self._shipment_fk_for_lookup(wn, shipment_id)
        lookup_thread: str | None = self._clean(thread_id)
        if wn in ("ratecon", "pod_lifecycle"):
            lookup_thread = None

        def _lookup(repo: WorkflowLifecyclesRepository) -> dict:
            lifecycle_id = repo.find_existing_lifecycle_id_tx(
                tenant_id=tid,
                workflow_name=wn,
                tender_id=tender_uuid,
                thread_id=lookup_thread,
                shipment_id=ship_key,
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
        if workflow_name_clean in ("ratecon", "pod_lifecycle"):
            thread_id = None
        shipment_id = self._extract_db_shipment_id(payload)

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

    def read_correlation_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        lid = self._clean(lifecycle_id)
        if not lid:
            return None
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.read_correlation_by_id(lid)
        return run_with_repos(
            lambda repos: self._repo(repos).read_correlation_by_id(lid)
        )

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

    def patch_metadata(
        self,
        *,
        lifecycle_id: str,
        metadata_patch: dict[str, Any],
    ) -> bool:
        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")
        if not metadata_patch:
            return False
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.patch_metadata(
                lifecycle_id=lid,
                metadata_patch=metadata_patch,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).patch_metadata(
                lifecycle_id=lid,
                metadata_patch=metadata_patch,
            )
        )

    def claim_appointment_draft_send_queued(
        self,
        *,
        lifecycle_id: str,
        expected_tenant_id: str,
    ) -> str:
        """Claim portal draft send (``metadata.draft_send_queued``) in one transaction."""
        lid = self._clean(lifecycle_id)
        tenant_id = self._clean(expected_tenant_id)
        if not lid or not tenant_id:
            return "not_found"
        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.claim_appointment_draft_send_queued(
                lifecycle_id=lid,
                expected_tenant_id=tenant_id,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).claim_appointment_draft_send_queued(
                lifecycle_id=lid,
                expected_tenant_id=tenant_id,
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

    def find_in_progress_lifecycle_id(
        self,
        *,
        tenant_id: str,
        policy: WorkflowCancellationPolicy,
        shipment_id: str,
    ) -> str | None:
        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        sid = self._uuid_or_none(shipment_id)
        if not tid or not sid:
            return None

        def _lookup(repo: WorkflowLifecyclesRepository) -> str | None:
            return repo.find_in_progress_lifecycle_id(
                tenant_id=tid,
                workflow_name=policy.workflow_name,
                shipment_id=sid,
                in_progress_statuses=policy.in_progress_status_values(),
                excluded_sub_statuses=policy.excluded_sub_status_values(),
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def find_latest_non_cancelled_lifecycle_id(
        self,
        *,
        tenant_id: str,
        policy: WorkflowCancellationPolicy,
        shipment_id: str,
    ) -> str | None:
        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        sid = self._uuid_or_none(shipment_id)
        if not tid or not sid:
            return None

        def _lookup(repo: WorkflowLifecyclesRepository) -> str | None:
            return repo.find_latest_non_cancelled_lifecycle_id(
                tenant_id=tid,
                workflow_name=policy.workflow_name,
                shipment_id=sid,
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def find_active_driver_assignment_lifecycle_id(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> str | None:
        from app.configs.workflow_cancellation_policies import (
            DRIVER_ASSIGNMENT_CANCEL_POLICY,
        )

        return self.find_in_progress_lifecycle_id(
            tenant_id=tenant_id,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            shipment_id=shipment_id,
        )

    def has_success_terminal_driver_assignment_lifecycle(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> bool:
        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        sid = self._uuid_or_none(shipment_id)
        if not tid or not sid:
            return False

        def _lookup(repo: WorkflowLifecyclesRepository) -> bool:
            return repo.has_success_terminal_driver_assignment_lifecycle(
                tenant_id=tid,
                shipment_id=sid,
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def resolve_driver_assignment_cycle(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> LifecycleResolution:
        tenant_id_clean = self._clean(tenant_id)
        if not tenant_id_clean:
            raise ValueError("tenant_id is required")

        db_tenant_id = resolve_graph_tenant_to_uuid(tenant_id_clean)
        if not db_tenant_id:
            raise ValueError(
                f"No matching tenants row for tenant_id={tenant_id_clean!r}"
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

        shipment_id = self._extract_db_shipment_id(payload)
        if not shipment_id:
            raise ValueError("shipments_row_id required for driver_assignment cycle")

        active_id = self.find_active_driver_assignment_lifecycle_id(
            tenant_id=tenant_id_clean,
            shipment_id=shipment_id,
        )
        if active_id:
            logger.warning(
                "resolve_driver_assignment_cycle refused insert: active lifecycle_id=%s shipment_id=%s",
                active_id,
                shipment_id,
            )
            return LifecycleResolution(
                workflow_lifecycle_id=active_id,
                existed=True,
            )

        def _insert(repo: WorkflowLifecyclesRepository) -> LifecycleResolution:
            new_id = repo.insert_driver_assignment_lifecycle(
                tenant_id=db_tenant_id,
                shipment_id=shipment_id,
            )
            return LifecycleResolution(
                workflow_lifecycle_id=new_id,
                existed=False,
            )

        if self._lifecycles_repo is not None:
            return _insert(self._lifecycles_repo)
        return run_with_repos(lambda repos: _insert(self._repo(repos)))

    def append_driver_assignment_sent_schedule_step(
        self,
        *,
        lifecycle_id: str,
        schedule_step: int,
    ) -> bool:
        """Track which schedule slots already sent (eligibility dedup after catch-up)."""
        lid = self._clean(lifecycle_id)
        if not lid:
            return False
        try:
            step = int(schedule_step)
        except (TypeError, ValueError):
            return False

        row = self.read_lifecycle_row_by_id(lid)
        merged = append_sent_schedule_step(
            sorted(sent_schedule_steps_from_metadata((row or {}).get("metadata") or {})),
            step,
        )
        patch = {"driver_assignment_sent_schedule_steps": merged}

        if self._lifecycles_repo is not None:
            return self._lifecycles_repo.patch_metadata(
                lifecycle_id=lid,
                metadata_patch=patch,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).patch_metadata(
                lifecycle_id=lid,
                metadata_patch=patch,
            )
        )

    def find_blocking_appointment_scheduling_lifecycle_id(
        self,
        *,
        tenant_id: str,
        turvo_shipment_number: str,
        workflow_name: str,
    ) -> str | None:
        from app.domain.appointment_scheduling.constants import (
            APPOINTMENT_SCHEDULING_WORKFLOW,
        )

        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        number = self._clean(turvo_shipment_number)
        wn = self._clean(workflow_name) or APPOINTMENT_SCHEDULING_WORKFLOW
        if not tid or not number:
            return None

        def _lookup(repo: WorkflowLifecyclesRepository) -> str | None:
            return repo.find_blocking_appointment_scheduling_lifecycle_id(
                tenant_id=tid,
                workflow_name=wn,
                shipment_number=number,
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def create_appointment_scheduling_lifecycle(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
        workflow_name: str,
    ) -> str:
        from app.domain.appointment_scheduling.constants import (
            APPOINTMENT_SCHEDULING_WORKFLOW,
        )

        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        sid = self._uuid_or_none(shipments_row_id)
        wn = self._clean(workflow_name) or APPOINTMENT_SCHEDULING_WORKFLOW
        if not tid or not sid:
            raise ValueError("tenant_id and shipments_row_id are required")

        def _insert(repo: WorkflowLifecyclesRepository) -> str:
            return repo.insert_appointment_scheduling_lifecycle(
                tenant_id=tid,
                workflow_name=wn,
                shipment_id=sid,
            )

        if self._lifecycles_repo is not None:
            return _insert(self._lifecycles_repo)
        return run_with_repos(lambda repos: _insert(self._repo(repos)))

    def find_awaiting_customer_reply_lifecycle_id(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
        workflow_name: str | None = None,
    ) -> str | None:
        from app.domain.appointment_scheduling.constants import (
            APPOINTMENT_SCHEDULING_WORKFLOW,
        )

        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        sid = self._uuid_or_none(shipments_row_id)
        wn = self._clean(workflow_name) or APPOINTMENT_SCHEDULING_WORKFLOW
        if not tid or not sid:
            return None

        def _lookup(repo: WorkflowLifecyclesRepository) -> str | None:
            return repo.find_awaiting_customer_reply_lifecycle_id(
                tenant_id=tid,
                shipment_id=sid,
                workflow_name=wn,
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))

    def find_awaiting_customer_reply_by_appt_subject_token(
        self,
        *,
        tenant_id: str,
        subject_token: str,
        workflow_name: str | None = None,
    ) -> str | None:
        from app.domain.appointment_scheduling.constants import (
            APPOINTMENT_SCHEDULING_WORKFLOW,
        )

        tid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        token = self._clean(subject_token)
        wn = self._clean(workflow_name) or APPOINTMENT_SCHEDULING_WORKFLOW
        if not tid or not token:
            return None

        def _lookup(repo: WorkflowLifecyclesRepository) -> str | None:
            return repo.find_awaiting_customer_reply_by_appt_subject_token(
                tenant_id=tid,
                subject_token=token,
                workflow_name=wn,
            )

        if self._lifecycles_repo is not None:
            return _lookup(self._lifecycles_repo)
        return run_with_repos(lambda repos: _lookup(self._repo(repos)))