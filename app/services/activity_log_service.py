"""Record workflow audit events in ``activity_logs``.

Callable from any workflow node, webhook handler, or Celery task. Resolves graph tenant
keys (e.g. ``gelita``) to ``tenants.id`` before insert. Failures are logged and return
``None`` so graph execution is not blocked.

Use ``record_action``, ``record_status_change``, ``record_sub_status_change``, or
``record_sequence`` for lifecycle-scoped rows. ``record_activity`` remains for legacy
non-lifecycle event type strings only.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.activity_log_write import (
    ActivityLogSequence,
    ActivityLogSequenceResult,
    ActivityLogStep,
    ActivityLogWrite,
)
from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
)
from app.models.activity_type import ActivityType, ActorType, SYSTEM_ACTOR_ID
from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


class ActivityLogService:
    def __init__(self, repository: Optional[ActivityLogsRepository] = None) -> None:
        self._repository = repository

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

    def _validate_scope(
        self,
        write: ActivityLogWrite,
        *,
        portal_lifecycle_scoped: bool = False,
    ) -> tuple[str | None, str | None, str] | None:
        tenant_id = self._clean(write.tenant_id)
        if not tenant_id:
            logger.warning("activity_log skipped: tenant_id is required")
            return None

        wl = self._uuid_or_none(
            write.workflow_lifecycle_id, field_name="workflow_lifecycle_id"
        )
        wr = self._uuid_or_none(write.workflow_run_id, field_name="workflow_run_id")

        if wl is None:
            logger.warning(
                "activity_log skipped: workflow_lifecycle_id is required "
                "(tenant_id=%r)",
                write.tenant_id,
            )
            return None

        if wr:
            return wl, wr, tenant_id

        if portal_lifecycle_scoped:
            return wl, None, tenant_id

        logger.warning(
            "activity_log skipped: invalid workflow scope "
            "(tenant_id=%r lifecycle_id=%r run_id=%r)",
            write.tenant_id,
            write.workflow_lifecycle_id,
            write.workflow_run_id,
        )
        return None

    def _to_command(
        self,
        write: ActivityLogWrite,
        *,
        activity_type: ActivityType,
        update_lifecycle: bool | None = None,
        portal_lifecycle_scoped: bool = False,
    ) -> LifecycleTransitionCommand | None:
        scope = self._validate_scope(
            write,
            portal_lifecycle_scoped=portal_lifecycle_scoped,
        )
        if scope is None:
            return None
        wl, wr, tenant_id = scope

        if update_lifecycle is None:
            update_lifecycle = activity_type != ActivityType.ACTION

        return LifecycleTransitionCommand(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl,
            workflow_run_id=wr,
            activity_type=activity_type,
            description=self._clean(write.description),
            metadata=write.metadata if write.metadata is not None else {},
            actor_type=write.actor_type or ActorType.SYSTEM,
            actor_id=write.actor_id,
            to_status=write.to_status,
            to_sub_status=write.to_sub_status,
            from_status=write.from_status,
            from_sub_status=write.from_sub_status,
            update_lifecycle=update_lifecycle,
            record_activity=write.record_log,
            require_lifecycle_row=write.require_lifecycle_row,
            email_thread_id=write.email_thread_id,
            communication_id=self._uuid_or_none(
                write.communication_id, field_name="communication_id"
            ),
        )

    def _step_to_command(
        self,
        sequence: ActivityLogSequence,
        step: ActivityLogStep,
        *,
        wl: str,
        wr: str | None,
        tenant_id: str,
    ) -> LifecycleTransitionCommand:
        if step.update_lifecycle is None:
            update_lifecycle = step.activity_type != ActivityType.ACTION
        else:
            update_lifecycle = step.update_lifecycle

        return LifecycleTransitionCommand(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl,
            workflow_run_id=wr,
            activity_type=step.activity_type,
            description=self._clean(step.description),
            metadata=step.metadata if step.metadata is not None else {},
            actor_type=sequence.actor_type or ActorType.SYSTEM,
            actor_id=sequence.actor_id,
            to_status=step.to_status,
            to_sub_status=step.to_sub_status,
            from_status=step.from_status,
            from_sub_status=step.from_sub_status,
            update_lifecycle=update_lifecycle,
            record_activity=step.record_log,
            require_lifecycle_row=sequence.require_lifecycle_row,
            email_thread_id=sequence.email_thread_id,
            communication_id=self._uuid_or_none(
                step.communication_id, field_name="communication_id"
            ),
        )

    def _apply_command(
        self, command: LifecycleTransitionCommand | None
    ) -> str | None:
        if command is None:
            return None
        try:
            lifecycle_transition_service = LifecycleTransitionService()
            result = lifecycle_transition_service.apply(command)
            return result.activity_log_id
        except LifecycleTransitionError as exc:
            logger.warning(
                "activity_log skipped lifecycle transition: %s",
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "activity_log lifecycle transition failed activity_type=%s lifecycle_id=%s",
                command.activity_type.value,
                command.workflow_lifecycle_id,
            )
            return None

    def _apply_sequence_commands(
        self, commands: tuple[LifecycleTransitionCommand, ...]
    ) -> ActivityLogSequenceResult | None:
        if not commands:
            return ActivityLogSequenceResult(activity_log_ids=[], lifecycle_updated=False)
        try:
            lifecycle_transition_service = LifecycleTransitionService()
            result = lifecycle_transition_service.apply_sequence(*commands)
            return ActivityLogSequenceResult(
                activity_log_ids=result.activity_log_ids,
                lifecycle_updated=result.lifecycle_updated,
            )
        except LifecycleTransitionError as exc:
            logger.warning(
                "activity_log sequence skipped lifecycle transition: %s",
                exc,
            )
            return None
        except Exception:
            logger.exception(
                "activity_log sequence failed lifecycle_id=%s",
                commands[0].workflow_lifecycle_id,
            )
            return None

    def record_action(self, write: ActivityLogWrite) -> str | None:
        """One ``action`` row; snapshots lifecycle status/sub_status (no lifecycle update)."""
        wl = self._uuid_or_none(
            write.workflow_lifecycle_id, field_name="workflow_lifecycle_id"
        )
        wr = self._uuid_or_none(write.workflow_run_id, field_name="workflow_run_id")
        command = self._to_command(
            write,
            activity_type=ActivityType.ACTION,
            update_lifecycle=False,
            portal_lifecycle_scoped=wr is None,
        )
        return self._apply_command(command)

    def record_status_change(self, write: ActivityLogWrite) -> str | None:
        """
        One ``status_change`` row; may set both ``to_status`` and ``to_sub_status``.

        If only ``to_sub_status`` is set, use ``record_sub_status_change`` instead.
        """
        if write.to_status is None and write.to_sub_status is not None:
            logger.warning(
                "record_status_change: to_status missing but to_sub_status set; "
                "use record_sub_status_change"
            )
            return self.record_sub_status_change(write)
        command = self._to_command(write, activity_type=ActivityType.STATUS_CHANGE)
        return self._apply_command(command)

    def record_sub_status_change(self, write: ActivityLogWrite) -> str | None:
        """One ``sub_status_change`` row when only sub_status moves."""
        if write.to_status is not None:
            logger.info(
                "record_sub_status_change: to_status set; coercing to status_change"
            )
            return self.record_status_change(write)
        command = self._to_command(
            write, activity_type=ActivityType.SUB_STATUS_CHANGE
        )
        return self._apply_command(command)

    def record_sequence(self, sequence: ActivityLogSequence) -> ActivityLogSequenceResult | None:
        """Multiple log rows (+ lifecycle updates) in a single database transaction."""
        if not sequence.steps:
            return ActivityLogSequenceResult(
                activity_log_ids=[], lifecycle_updated=False
            )

        run_id = self._uuid_or_none(
            sequence.workflow_run_id, field_name="workflow_run_id"
        )
        scope = self._validate_scope(
            ActivityLogWrite(
                tenant_id=sequence.tenant_id,
                workflow_lifecycle_id=sequence.workflow_lifecycle_id,
                workflow_run_id=sequence.workflow_run_id,
            ),
            portal_lifecycle_scoped=run_id is None,
        )
        if scope is None:
            return None
        wl, wr, tenant_id = scope

        commands = tuple(
            self._step_to_command(sequence, step, wl=wl, wr=wr, tenant_id=tenant_id)
            for step in sequence.steps
        )
        return self._apply_sequence_commands(commands)

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
        Legacy/generic insert. Prefer ``record_action`` / ``record_status_change``.

        Routes ``action``, ``status_change``, and ``sub_status_change`` through the
        lifecycle transition service. Other ``activity_type`` strings use a direct
        repository insert (no lifecycle update).
        """
        at = self._clean(activity_type)
        if not at:
            logger.warning("activity_log skipped: activity_type is required")
            return None

        wl = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        wr = self._uuid_or_none(workflow_run_id, field_name="workflow_run_id")
        if not wl or not wr:
            logger.warning(
                "activity_log skipped: workflow_lifecycle_id and workflow_run_id required "
                "(activity_type=%r)",
                at,
            )
            return None

        tid_uuid = resolve_graph_tenant_to_uuid(self._clean(tenant_id))
        if not tid_uuid:
            if self._clean(tenant_id):
                logger.warning(
                    "activity_log skipped: cannot resolve tenant_id=%r to tenants.id (UUID)",
                    tenant_id,
                )
            return None

        if at == ActivityType.ACTION.value:
            return self.record_action(
                ActivityLogWrite(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl,
                    workflow_run_id=wr,
                    description=description,
                    metadata=metadata,
                    actor_type=ActorType(self._clean(actor_type) or ActorType.SYSTEM),
                    actor_id=actor_id,
                )
            )
        if at == ActivityType.STATUS_CHANGE.value:
            from app.models.status import StatusSubType, StatusType

            return self.record_status_change(
                ActivityLogWrite(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl,
                    workflow_run_id=wr,
                    description=description,
                    metadata=metadata,
                    actor_type=ActorType(self._clean(actor_type) or ActorType.SYSTEM),
                    actor_id=actor_id,
                    to_status=StatusType(to_status) if to_status else None,
                    to_sub_status=StatusSubType(to_sub_status) if to_sub_status else None,
                    from_status=StatusType(from_status) if from_status else None,
                    from_sub_status=StatusSubType(from_sub_status) if from_sub_status else None,
                )
            )
        if at == ActivityType.SUB_STATUS_CHANGE.value:
            from app.models.status import StatusSubType, StatusType

            return self.record_sub_status_change(
                ActivityLogWrite(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl,
                    workflow_run_id=wr,
                    description=description,
                    metadata=metadata,
                    actor_type=ActorType(self._clean(actor_type) or ActorType.SYSTEM),
                    actor_id=actor_id,
                    to_sub_status=StatusSubType(to_sub_status) if to_sub_status else None,
                    from_status=StatusType(from_status) if from_status else None,
                    from_sub_status=StatusSubType(from_sub_status) if from_sub_status else None,
                )
            )

        actor = self._uuid_or_none(actor_id, field_name="actor_id")
        actor_type_clean = self._clean(actor_type)
        if not actor and actor_type_clean == ActorType.SYSTEM.value:
            actor = SYSTEM_ACTOR_ID

        row = {
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

        try:
            if self._repository is not None:
                return self._repository.insert(row)
            return run_with_repos(lambda repos: repos.activity_logs.insert(row))
        except Exception:
            logger.exception(
                "activity_log insert failed activity_type=%r tenant_id=%s",
                at,
                tid_uuid,
            )
            return None

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
