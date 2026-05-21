"""Record workflow audit events in ``activity_logs``.

Callable from any workflow node, webhook handler, or Celery task. Resolves graph tenant
keys (e.g. ``gelita``) to ``tenants.id`` before insert. Failures are logged and return
``None`` so graph execution is not blocked.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.domain.activity_log_descriptions import (
    format_status_updated_to_processing,
    format_tender_created_action,
)
from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)

# Sentinel UUID for ``actor_type=system`` when no user initiated the action (no FK).
SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000001"


class ActivityLogService:
    def __init__(self, repository: Optional[ActivityLogsRepository] = None) -> None:
        self._repository = repository or ActivityLogsRepository()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "value"):
            value = value.value
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _uuid_or_none(value: Any, *, field_name: str) -> str | None:
        raw = ActivityLogService._clean(value)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            logger.warning(
                "activity_log skipped invalid %s=%r (expected UUID)",
                field_name,
                value,
            )
            return None

    def _tenant_uuid_or_none(self, tenant_id: str | None) -> str | None:
        return resolve_graph_tenant_to_uuid(self._clean(tenant_id))

    def record_activity(
        self,
        *,
        tenant_id: str,
        activity_type: str,
        workflow_lifecycle_id: str | None = None,
        workflow_run_id: str | None = None,
        description: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        from_sub_status: str | None = None,
        to_sub_status: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Insert one ``activity_logs`` row.

        Returns the new row id, or ``None`` when required fields are missing or insert fails.
        """
        tid_uuid = self._tenant_uuid_or_none(tenant_id)
        at = self._clean(activity_type)
        if not tid_uuid:
            if self._clean(tenant_id):
                logger.warning(
                    "activity_log skipped: cannot resolve tenant_id=%r to tenants.id (UUID)",
                    tenant_id,
                )
            return None
        if not at:
            logger.warning("activity_log skipped: activity_type is required")
            return None

        wl = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        wr = self._uuid_or_none(workflow_run_id, field_name="workflow_run_id")
        if not wl or not wr:
            logger.warning(
                "activity_log skipped: workflow_lifecycle_id and workflow_run_id required "
                "(activity_type=%r tenant_id=%s)",
                at,
                tid_uuid,
            )
            return None

        actor = self._uuid_or_none(actor_id, field_name="actor_id")
        actor_type_clean = self._clean(actor_type)
        if not actor and actor_type_clean == ActorType.SYSTEM.value:
            actor = SYSTEM_ACTOR_ID

        try:
            return self._repository.insert(
                {
                    "tenant_id": tid_uuid,
                    "workflow_lifecycle_id": wl,
                    "workflow_run_id": wr,
                    "activity_type": at,
                    "description": self._clean(description),
                    "from_status": self._clean(from_status),
                    "to_status": self._clean(to_status),
                    "from_sub_status": self._clean(from_sub_status),
                    "to_sub_status": self._clean(to_sub_status),
                    "actor_type": self._clean(actor_type),
                    "actor_id": actor,
                    "metadata": metadata if metadata is not None else {},
                }
            )
        except Exception:
            logger.exception(
                "activity_log insert failed activity_type=%r tenant_id=%s",
                at,
                tid_uuid,
            )
            return None

    def record_tender_created_action(
        self,
        *,
        tenant_id: str,
        tender_id: str,
        order_number: str,
        customer_name: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str,
    ) -> str | None:
        """Action log for a new tender on the workflow run that processes it."""
        return self.record_activity(
            tenant_id=tenant_id,
            activity_type=ActivityType.ACTION,
            workflow_lifecycle_id=workflow_lifecycle_id,
            workflow_run_id=workflow_run_id,
            description=format_tender_created_action(
                tender_id=tender_id,
                order_number=order_number,
                customer_name=customer_name,
            ),
            from_status=StatusType.NONE,
            to_status=StatusType.NONE,
            from_sub_status=StatusSubType.NONE,
            to_sub_status=StatusSubType.NONE,
            actor_type=ActorType.SYSTEM,
            metadata={"tender_id": tender_id},
        )

    def record_tender_processing_status_change(
        self,
        *,
        tenant_id: str,
        tender_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str,
    ) -> str | None:
        """Status_change log: processing / tender_created on the same workflow run."""
        
        wl = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        if not wl:
            return None 
        lifecycle_svc = WorkflowLifecycleService()
        lifecycle_svc.update_lifecycle_status(
            lifecycle_id=wl,
            status=StatusType.PROCESSING,
            sub_status=StatusSubType.TENDER_CREATED,
        )

        return self.record_activity(
            tenant_id=tenant_id,
            activity_type=ActivityType.STATUS_CHANGE,
            workflow_lifecycle_id=workflow_lifecycle_id,
            workflow_run_id=workflow_run_id,
            description=format_status_updated_to_processing(),
            from_status=StatusType.NONE,
            to_status=StatusType.PROCESSING,
            from_sub_status=StatusSubType.NONE,
            to_sub_status=StatusSubType.TENDER_CREATED,
            actor_type=ActorType.SYSTEM,
            metadata={"tender_id": tender_id},
        )

    def record_from_workflow_state(
        self,
        state: Any,
        *,
        activity_type: str,
        description: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        from_sub_status: str | None = None,
        to_sub_status: str | None = None,
        actor_type: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        workflow_lifecycle_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> str | None:
        """Log from a LangGraph ``WorkflowState`` (reads tenant/lifecycle/run from state)."""

        data = getattr(state, "data", None) or {}
        tenant_raw = data.get("tenant_id") if isinstance(data, dict) else None
        if not tenant_raw:
            tenant_raw = getattr(state, "tenant_id", None)

        wl = workflow_lifecycle_id
        if wl is None and isinstance(data, dict):
            wl = data.get("workflow_lifecycle_id")

        wr = workflow_run_id
        if wr is None:
            wr = getattr(state, "execution_id", None)

        return self.record_activity(
            tenant_id=str(tenant_raw or ""),
            activity_type=activity_type,
            workflow_lifecycle_id=wl,
            workflow_run_id=wr,
            description=description,
            from_status=from_status,
            to_status=to_status,
            from_sub_status=from_sub_status,
            to_sub_status=to_sub_status,
            actor_type=actor_type,
            actor_id=actor_id,
            metadata=metadata,
        )
