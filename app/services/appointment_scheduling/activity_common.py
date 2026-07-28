"""Shared helpers for appointment scheduling activity / lifecycle transitions."""

from __future__ import annotations

import dataclasses
from typing import Any

from app.core.logger import get_logger
from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
    LifecycleTransitionResult,
)
from app.domain.status_parsing import status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


def scope_ids(state) -> tuple[str, str, str] | None:
    data = getattr(state, "data", None) or {}
    if not isinstance(data, dict):
        data = {}
    wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = str(getattr(state, "tenant_id", None) or data.get("tenant_id") or "").strip()
    run_id = str(getattr(state, "execution_id", None) or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def lifecycle_already_started(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    status = status_type_from_db(row.get("status"))
    return status not in (None, StatusType.NONE)


def build_sub_status_transition_command(
    *,
    tenant_id: str,
    workflow_lifecycle_id: str,
    workflow_run_id: str,
    current_status: StatusType | None,
    new_sub: StatusSubType,
) -> LifecycleTransitionCommand:
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        return LifecycleTransitionCommand(
            tenant_id=tenant_id,
            workflow_lifecycle_id=workflow_lifecycle_id,
            workflow_run_id=workflow_run_id,
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
        )
    return LifecycleTransitionCommand(
        tenant_id=tenant_id,
        workflow_lifecycle_id=workflow_lifecycle_id,
        workflow_run_id=workflow_run_id,
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=to_status,
        to_sub_status=new_sub,
    )


class SchedulingActivityDeps:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        transition_service: LifecycleTransitionService | None = None,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self.lifecycle = lifecycle_service or WorkflowLifecycleService()
        self.transitions = transition_service or LifecycleTransitionService()
        self.activity_log = activity_log_service or ActivityLogService()

    def apply(self, command: LifecycleTransitionCommand) -> LifecycleTransitionResult | None:
        try:
            return self.transitions.apply(command)
        except LifecycleTransitionError as exc:
            logger.warning("scheduling activity transition skipped: %s", exc)
        except Exception:
            logger.exception(
                "scheduling activity transition failed activity_type=%s lifecycle_id=%s",
                command.activity_type.value,
                command.workflow_lifecycle_id,
            )
        return None

    def apply_sequence(self, *commands: LifecycleTransitionCommand) -> None:
        if not commands:
            return
        try:
            self.transitions.apply_sequence(*commands)
        except LifecycleTransitionError as exc:
            logger.warning("scheduling activity sequence skipped: %s", exc)
        except Exception:
            logger.exception(
                "scheduling activity sequence failed lifecycle_id=%s",
                commands[0].workflow_lifecycle_id,
            )

    def action_from_state(
        self,
        state,
        *,
        description: str,
        communication_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor_type: ActorType | None = None,
        actor_id: str | None = None,
    ) -> LifecycleTransitionCommand:
        """ACTION log: link email only when ``communication_id`` is passed."""
        if communication_id:
            return LifecycleTransitionCommand.from_workflow_state(
                state,
                activity_type=ActivityType.ACTION,
                description=description,
                update_lifecycle=False,
                communication_id=communication_id,
                metadata=metadata,
                actor_type=actor_type or ActorType.SYSTEM,
                actor_id=actor_id,
            )
        # Omit communication_id so from_workflow_state may inherit, then clear it.
        command = LifecycleTransitionCommand.from_workflow_state(
            state,
            activity_type=ActivityType.ACTION,
            description=description,
            update_lifecycle=False,
            metadata=metadata,
            actor_type=actor_type or ActorType.SYSTEM,
            actor_id=actor_id,
        )
        return dataclasses.replace(command, communication_id=None)


__all__ = (
    "SchedulingActivityDeps",
    "build_sub_status_transition_command",
    "lifecycle_already_started",
    "scope_ids",
)
