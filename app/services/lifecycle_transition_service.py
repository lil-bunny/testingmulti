"""Atomic workflow lifecycle updates and ``activity_logs`` writes (single front door)."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
    LifecycleTransitionResult,
)
from app.domain.activity_log_fields import build_activity_log_status_fields
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType, SYSTEM_ACTOR_ID
from app.models.status import StatusSubType, StatusType
from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.repositories.unit_of_work import unit_of_work
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
logger = get_logger(__name__)


class LifecycleTransitionService:
    def __init__(
        self,
        *,
        lifecycles_repo: WorkflowLifecyclesRepository | None = None,
        activity_logs_repo: ActivityLogsRepository | None = None,
    ) -> None:
        self._lifecycles = lifecycles_repo or WorkflowLifecyclesRepository()
        self._activity_logs = activity_logs_repo or ActivityLogsRepository()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "value"):
            value = value.value
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _uuid_or_raise(value: str, *, field_name: str) -> str:
        raw = LifecycleTransitionService._clean(value)
        if not raw:
            raise LifecycleTransitionError(f"{field_name} is required")
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError) as exc:
            raise LifecycleTransitionError(
                f"invalid {field_name}={value!r} (expected UUID)"
            ) from exc

    def apply(self, command: LifecycleTransitionCommand) -> LifecycleTransitionResult:
        tenant_uuid = resolve_graph_tenant_to_uuid(self._clean(command.tenant_id))
        if not tenant_uuid:
            raise LifecycleTransitionError(
                f"cannot resolve tenant_id={command.tenant_id!r} to tenants.id"
            )

        lifecycle_id = self._uuid_or_raise(
            command.workflow_lifecycle_id,
            field_name="workflow_lifecycle_id",
        )
        run_id = self._uuid_or_raise(
            command.workflow_run_id,
            field_name="workflow_run_id",
        )

        actor_type = command.actor_type or ActorType.SYSTEM
        actor_id = self._clean(command.actor_id)
        if not actor_id and actor_type == ActorType.SYSTEM:
            actor_id = SYSTEM_ACTOR_ID

        with unit_of_work() as conn:
            row = self._lifecycles.get_for_update(conn, lifecycle_id=lifecycle_id)
            if row is None:
                if command.require_lifecycle_row:
                    raise LifecycleTransitionError(
                        f"workflow_lifecycle not found id={lifecycle_id}"
                    )
                current_status: StatusType | None = command.from_status
                current_sub: StatusSubType | None = command.from_sub_status
            elif command.activity_type == ActivityType.ACTION:
                current_status = status_type_from_db(row.get("status"))
                current_sub = sub_status_type_from_db(row.get("sub_status"))
            else:
                current_status = command.from_status or status_type_from_db(
                    row.get("status")
                )
                current_sub = command.from_sub_status or sub_status_type_from_db(
                    row.get("sub_status")
                )

            log_from_status, log_to_status, log_from_sub, log_to_sub = (
                build_activity_log_status_fields(
                    command,
                    current_status=current_status,
                    current_sub=current_sub,
                )
            )

            lifecycle_updated = False
            update_lifecycle = (
                command.update_lifecycle
                and command.activity_type != ActivityType.ACTION
            )
            if update_lifecycle and row is not None:
                thread = self._clean(command.email_thread_id)
                if thread:
                    self._lifecycles.update_email_thread_id(
                        conn,
                        lifecycle_id=lifecycle_id,
                        email_thread_id=thread,
                    )
                if command.to_status is not None or command.to_sub_status is not None:
                    lifecycle_updated = self._lifecycles.update_status(
                        conn,
                        lifecycle_id=lifecycle_id,
                        status=command.to_status,
                        sub_status=command.to_sub_status,
                    )

            activity_log_id: str | None = None
            if command.record_activity:
                activity_log_id = self._activity_logs.insert_with_connection(
                    conn,
                    {
                        "tenant_id": tenant_uuid,
                        "workflow_lifecycle_id": lifecycle_id,
                        "workflow_run_id": run_id,
                        "activity_type": command.activity_type.value,
                        "description": self._clean(command.description),
                        "from_status": (
                            log_from_status.value if log_from_status is not None else None
                        ),
                        "to_status": (
                            log_to_status.value if log_to_status is not None else None
                        ),
                        "from_sub_status": (
                            log_from_sub.value if log_from_sub is not None else None
                        ),
                        "to_sub_status": (
                            log_to_sub.value if log_to_sub is not None else None
                        ),
                        "actor_type": actor_type.value,
                        "actor_id": actor_id,
                        "metadata": command.metadata if command.metadata is not None else {},
                    },
                )

        logger.info(
            "lifecycle_transition applied lifecycle_id=%s activity_type=%s "
            "lifecycle_updated=%s activity_log_id=%s",
            lifecycle_id,
            command.activity_type.value,
            lifecycle_updated,
            activity_log_id,
        )
        return LifecycleTransitionResult(
            lifecycle_updated=lifecycle_updated,
            activity_log_id=activity_log_id,
            from_status=log_from_status,
            from_sub_status=log_from_sub,
            to_status=log_to_status,
            to_sub_status=log_to_sub,
        )

    def apply_from_state(
        self,
        state: Any,
        **kwargs: Any,
    ) -> LifecycleTransitionResult:
        """Build ``LifecycleTransitionCommand`` from graph state and apply."""
        command = LifecycleTransitionCommand.from_workflow_state(state, **kwargs)
        return self.apply(command)
