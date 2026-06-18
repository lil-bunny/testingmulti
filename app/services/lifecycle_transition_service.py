"""Atomic workflow lifecycle updates and ``activity_logs`` writes (single front door)."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.db import db_scope, db_transaction
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.activity_log_descriptions import generate_activity_log_description
from app.domain.activity_log_fields import build_activity_log_status_fields
from app.domain.lifecycle_transition import (
    LifecycleTransitionCommand,
    LifecycleTransitionError,
    LifecycleTransitionResult,
    LifecycleTransitionSequenceResult,
)
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType, SYSTEM_ACTOR_ID, is_snapshot_activity_type
from app.models.pause_type import PauseType
from app.models.status import StatusSubType, StatusType
from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.repositories.workflow_lifecycles_repository import (
    LifecycleUpdate,
    WorkflowLifecyclesRepository,
)


@dataclass(frozen=True)
class _PauseContext:
    """Sequence-wide pause decision: set on any EXCEPTION, else clear on lifecycle write."""

    has_exception: bool
    pause_type: PauseType | None


def _resolve_pause_context(
    commands: tuple[LifecycleTransitionCommand, ...],
) -> _PauseContext:
    has_exception = False
    pause_type: PauseType | None = None
    for command in commands:
        if command.activity_type is ActivityType.EXCEPTION:
            has_exception = True
            if pause_type is None and command.pause_type is not None:
                pause_type = command.pause_type
    if has_exception and pause_type is None:
        pause_type = PauseType.SYSTEM_ERROR
    return _PauseContext(has_exception=has_exception, pause_type=pause_type)

logger = get_logger(__name__)


class LifecycleTransitionService:
    def __init__(
        self,
        *,
        lifecycles_repo: WorkflowLifecyclesRepository | None = None,
        activity_logs_repo: ActivityLogsRepository | None = None,
    ) -> None:
        self._lifecycles = lifecycles_repo
        self._activity_logs = activity_logs_repo

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

    def _resolve_activity_description(
        self,
        command: LifecycleTransitionCommand,
        *,
        log_from_status: StatusType,
        log_to_status: StatusType,
        log_from_sub: StatusSubType,
        log_to_sub: StatusSubType,
    ) -> str | None:
        generated = generate_activity_log_description(
            activity_type=command.activity_type,
            from_status=log_from_status,
            to_status=log_to_status,
            from_sub_status=log_from_sub,
            to_sub_status=log_to_sub,
        )
        if generated is not None:
            return generated
        return self._clean(command.description)

    def _insert_activity_row(
        self,
        activity_logs: ActivityLogsRepository,
        *,
        tenant_uuid: str,
        lifecycle_id: str | None,
        run_id: str | None,
        command: LifecycleTransitionCommand,
        actor_type: ActorType,
        actor_id: str,
        log_from_status: StatusType,
        log_to_status: StatusType,
        log_from_sub: StatusSubType,
        log_to_sub: StatusSubType,
    ) -> str:
        return activity_logs.insert(
            {
                "tenant_id": tenant_uuid,
                "workflow_lifecycle_id": lifecycle_id,
                "workflow_run_id": run_id,
                "activity_type": command.activity_type.value,
                "description": self._resolve_activity_description(
                    command,
                    log_from_status=log_from_status,
                    log_to_status=log_to_status,
                    log_from_sub=log_from_sub,
                    log_to_sub=log_to_sub,
                ),
                "from_status": log_from_status.value,
                "to_status": log_to_status.value,
                "from_sub_status": log_from_sub.value,
                "to_sub_status": log_to_sub.value,
                "actor_type": actor_type.value,
                "actor_id": actor_id,
                "metadata": command.metadata if command.metadata is not None else {},
                "communication_id": command.communication_id,
            },
        )

    def _resolve_current_status(
        self,
        command: LifecycleTransitionCommand,
        row: dict[str, Any] | None,
    ) -> tuple[StatusType | None, StatusSubType | None]:
        if row is None:
            return command.from_status, command.from_sub_status
        if is_snapshot_activity_type(command.activity_type):
            return (
                status_type_from_db(row.get("status")),
                sub_status_type_from_db(row.get("sub_status")),
            )
        return (
            command.from_status or status_type_from_db(row.get("status")),
            command.from_sub_status or sub_status_type_from_db(row.get("sub_status")),
        )

    def _apply_one_step(
        self,
        lifecycles: WorkflowLifecyclesRepository,
        activity_logs: ActivityLogsRepository,
        *,
        command: LifecycleTransitionCommand,
        tenant_uuid: str,
        lifecycle_id: str | None,
        run_id: str | None,
        row: dict[str, Any] | None,
        current_status: StatusType | None,
        current_sub: StatusSubType | None,
        actor_type: ActorType,
        actor_id: str,
        pause_context: _PauseContext,
    ) -> tuple[
        str | None,
        bool,
        bool,
        StatusType | None,
        StatusSubType | None,
        StatusType,
        StatusType,
        StatusSubType,
        StatusSubType,
    ]:
        if is_snapshot_activity_type(command.activity_type):
            step_status, step_sub = self._resolve_current_status(command, row)
        else:
            step_status, step_sub = current_status, current_sub

        effective_command = command
        snapshot = is_snapshot_activity_type(command.activity_type)
        if (
            not snapshot
            and command.update_lifecycle
            and not pause_context.has_exception
            and command.to_status is None
            and command.to_sub_status is not None
            and step_status == StatusType.PENDING_REVIEW
        ):
            effective_command = dataclasses.replace(
                command, to_status=StatusType.PROCESSING
            )

        log_from_status, log_to_status, log_from_sub, log_to_sub = (
            build_activity_log_status_fields(
                effective_command,
                current_status=step_status,
                current_sub=step_sub,
            )
        )

        lifecycle_updated = False
        pause_written = False
        update_lifecycle_flag = (
            effective_command.update_lifecycle and not snapshot
        )
        next_status = step_status
        next_sub = step_sub
        if update_lifecycle_flag and row is not None:
            if (
                effective_command.to_status is not None
                or effective_command.to_sub_status is not None
            ):
                update = LifecycleUpdate(
                    status=effective_command.to_status,
                    sub_status=effective_command.to_sub_status,
                    pause_type=pause_context.pause_type
                    if pause_context.has_exception
                    else None,
                    clear_pause=not pause_context.has_exception,
                )
                lifecycle_updated = lifecycles.update_lifecycle(
                    lifecycle_id=lifecycle_id,
                    update=update,
                )
                pause_written = True
            next_status = log_to_status
            next_sub = log_to_sub

        activity_log_id: str | None = None
        if effective_command.record_activity:
            activity_log_id = self._insert_activity_row(
                activity_logs,
                tenant_uuid=tenant_uuid,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                command=effective_command,
                actor_type=actor_type,
                actor_id=actor_id,
                log_from_status=log_from_status,
                log_to_status=log_to_status,
                log_from_sub=log_from_sub,
                log_to_sub=log_to_sub,
            )

        return (
            activity_log_id,
            lifecycle_updated,
            pause_written,
            next_status,
            next_sub,
            log_from_status,
            log_to_status,
            log_from_sub,
            log_to_sub,
        )

    def _prepare_scope(
        self, command: LifecycleTransitionCommand
    ) -> tuple[str, str | None, str | None, ActorType, str]:
        tenant_uuid = resolve_graph_tenant_to_uuid(self._clean(command.tenant_id))
        if not tenant_uuid:
            raise LifecycleTransitionError(
                f"cannot resolve tenant_id={command.tenant_id!r} to tenants.id"
            )

        lifecycle_raw = self._clean(command.workflow_lifecycle_id)
        run_raw = self._clean(command.workflow_run_id)
        if lifecycle_raw is None:
            raise LifecycleTransitionError("workflow_lifecycle_id is required")
        lifecycle_id = self._uuid_or_raise(
            command.workflow_lifecycle_id,
            field_name="workflow_lifecycle_id",
        )
        run_id = (
            self._uuid_or_raise(
                command.workflow_run_id,
                field_name="workflow_run_id",
            )
            if run_raw is not None
            else None
        )

        actor_type = command.actor_type or ActorType.SYSTEM
        actor_id = self._clean(command.actor_id)
        if not actor_id and actor_type == ActorType.SYSTEM:
            actor_id = SYSTEM_ACTOR_ID
        return tenant_uuid, lifecycle_id, run_id, actor_type, actor_id

    def _apply_in_transaction(
        self,
        lifecycles: WorkflowLifecyclesRepository,
        activity_logs: ActivityLogsRepository,
        command: LifecycleTransitionCommand,
    ) -> LifecycleTransitionResult:
        tenant_uuid, lifecycle_id, run_id, actor_type, actor_id = self._prepare_scope(
            command
        )

        row: dict[str, Any] | None = None
        if lifecycle_id is not None:
            row = lifecycles.get_for_update(lifecycle_id=lifecycle_id)
            if row is None and command.require_lifecycle_row:
                raise LifecycleTransitionError(
                    f"workflow_lifecycle not found id={lifecycle_id}"
                )

        current_status, current_sub = self._resolve_current_status(command, row)
        pause_context = _resolve_pause_context((command,))
        (
            activity_log_id,
            lifecycle_updated,
            pause_written,
            _,
            _,
            log_from_status,
            log_to_status,
            log_from_sub,
            log_to_sub,
        ) = self._apply_one_step(
            lifecycles,
            activity_logs,
            command=command,
            tenant_uuid=tenant_uuid,
            lifecycle_id=lifecycle_id,
            run_id=run_id,
            row=row,
            current_status=current_status,
            current_sub=current_sub,
            actor_type=actor_type,
            actor_id=actor_id,
            pause_context=pause_context,
        )

        if (
            pause_context.has_exception
            and not pause_written
            and lifecycle_id is not None
            and row is not None
        ):
            lifecycles.update_lifecycle(
                lifecycle_id=lifecycle_id,
                update=LifecycleUpdate(pause_type=pause_context.pause_type),
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

    def apply(self, command: LifecycleTransitionCommand) -> LifecycleTransitionResult:
        if self._lifecycles is not None and self._activity_logs is not None:
            return self._apply_in_transaction(
                self._lifecycles, self._activity_logs, command
            )

        def _run(repos: Any) -> LifecycleTransitionResult:
            with db_transaction(repos.session):
                return self._apply_in_transaction(
                    repos.workflow_lifecycles,
                    repos.activity_logs,
                    command,
                )

        with db_scope() as repos:
            return _run(repos)

    def _apply_sequence_in_transaction(
        self,
        lifecycles: WorkflowLifecyclesRepository,
        activity_logs: ActivityLogsRepository,
        commands: tuple[LifecycleTransitionCommand, ...],
    ) -> LifecycleTransitionSequenceResult:
        first = commands[0]
        tenant_uuid, lifecycle_id, run_id, actor_type, actor_id = self._prepare_scope(
            first
        )

        activity_log_ids: list[str | None] = []
        any_lifecycle_updated = False

        if lifecycle_id is None:
            raise LifecycleTransitionError("apply_sequence requires workflow_lifecycle_id")

        row = lifecycles.get_for_update(lifecycle_id=lifecycle_id)
        if row is None and first.require_lifecycle_row:
            raise LifecycleTransitionError(
                f"workflow_lifecycle not found id={lifecycle_id}"
            )

        current_status, current_sub = self._resolve_current_status(first, row)
        pause_context = _resolve_pause_context(commands)
        any_pause_written = False

        for command in commands:
            cmd_tenant = resolve_graph_tenant_to_uuid(self._clean(command.tenant_id))
            if cmd_tenant != tenant_uuid:
                raise LifecycleTransitionError(
                    "apply_sequence commands must share tenant_id"
                )
            cmd_lifecycle = self._uuid_or_raise(
                command.workflow_lifecycle_id,
                field_name="workflow_lifecycle_id",
            )
            if cmd_lifecycle != lifecycle_id:
                raise LifecycleTransitionError(
                    "apply_sequence commands must share workflow_lifecycle_id"
                )
            cmd_run_raw = self._clean(command.workflow_run_id)
            if cmd_run_raw is None:
                cmd_run_id = None
            else:
                cmd_run_id = self._uuid_or_raise(
                    command.workflow_run_id,
                    field_name="workflow_run_id",
                )
            if cmd_run_id != run_id:
                raise LifecycleTransitionError(
                    "apply_sequence commands must share workflow_run_id"
                )

            step_actor_type = command.actor_type or actor_type
            step_actor_id = self._clean(command.actor_id) or actor_id

            (
                activity_log_id,
                lifecycle_updated,
                pause_written,
                current_status,
                current_sub,
                _,
                _,
                _,
                _,
            ) = self._apply_one_step(
                lifecycles,
                activity_logs,
                command=command,
                tenant_uuid=tenant_uuid,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                row=row,
                current_status=current_status,
                current_sub=current_sub,
                actor_type=step_actor_type,
                actor_id=step_actor_id,
                pause_context=pause_context,
            )
            activity_log_ids.append(activity_log_id)
            if lifecycle_updated:
                any_lifecycle_updated = True
            if pause_written:
                any_pause_written = True

        if (
            pause_context.has_exception
            and not any_pause_written
            and row is not None
        ):
            lifecycles.update_lifecycle(
                lifecycle_id=lifecycle_id,
                update=LifecycleUpdate(pause_type=pause_context.pause_type),
            )

        logger.info(
            "lifecycle_transition sequence applied lifecycle_id=%s steps=%s "
            "lifecycle_updated=%s activity_log_ids=%s",
            lifecycle_id,
            len(commands),
            any_lifecycle_updated,
            activity_log_ids,
        )
        return LifecycleTransitionSequenceResult(
            activity_log_ids=activity_log_ids,
            lifecycle_updated=any_lifecycle_updated,
        )

    def apply_sequence(
        self, *commands: LifecycleTransitionCommand
    ) -> LifecycleTransitionSequenceResult:
        if not commands:
            return LifecycleTransitionSequenceResult(
                activity_log_ids=[],
                lifecycle_updated=False,
            )

        if self._lifecycles is not None and self._activity_logs is not None:
            return self._apply_sequence_in_transaction(
                self._lifecycles, self._activity_logs, commands
            )

        def _run(repos: Any) -> LifecycleTransitionSequenceResult:
            with db_transaction(repos.session):
                return self._apply_sequence_in_transaction(
                    repos.workflow_lifecycles,
                    repos.activity_logs,
                    commands,
                )

        with db_scope() as repos:
            return _run(repos)

    def apply_from_state(
        self,
        state: Any,
        **kwargs: Any,
    ) -> LifecycleTransitionResult:
        """Build ``LifecycleTransitionCommand`` from graph state and apply."""
        command = LifecycleTransitionCommand.from_workflow_state(state, **kwargs)
        return self.apply(command)
