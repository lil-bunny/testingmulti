"""Atomic workflow lifecycle updates and ``activity_logs`` writes (single front door)."""

from __future__ import annotations

import uuid
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
from app.models.activity_type import ActivityType, ActorType, SYSTEM_ACTOR_ID
from app.models.status import StatusSubType, StatusType
from app.repositories.activity_logs_repository import ActivityLogsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository

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
        lifecycle_id: str,
        run_id: str,
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
        if command.activity_type == ActivityType.ACTION:
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
        lifecycle_id: str,
        run_id: str,
        row: dict[str, Any] | None,
        current_status: StatusType | None,
        current_sub: StatusSubType | None,
        actor_type: ActorType,
        actor_id: str,
    ) -> tuple[
        str | None,
        bool,
        StatusType | None,
        StatusSubType | None,
        StatusType,
        StatusType,
        StatusSubType,
        StatusSubType,
    ]:
        if command.activity_type == ActivityType.ACTION:
            step_status, step_sub = self._resolve_current_status(command, row)
        else:
            step_status, step_sub = current_status, current_sub

        log_from_status, log_to_status, log_from_sub, log_to_sub = (
            build_activity_log_status_fields(
                command,
                current_status=step_status,
                current_sub=step_sub,
            )
        )

        lifecycle_updated = False
        update_lifecycle = (
            command.update_lifecycle
            and command.activity_type != ActivityType.ACTION
        )
        next_status = step_status
        next_sub = step_sub
        if update_lifecycle and row is not None:
            thread = self._clean(command.email_thread_id)
            if thread:
                lifecycles.update_email_thread_id(
                    lifecycle_id=lifecycle_id,
                    email_thread_id=thread,
                )
            if command.to_status is not None or command.to_sub_status is not None:
                lifecycle_updated = lifecycles.update_status(
                    lifecycle_id=lifecycle_id,
                    status=command.to_status,
                    sub_status=command.to_sub_status,
                )
            next_status = log_to_status
            next_sub = log_to_sub

        activity_log_id: str | None = None
        if command.record_activity:
            activity_log_id = self._insert_activity_row(
                activity_logs,
                tenant_uuid=tenant_uuid,
                lifecycle_id=lifecycle_id,
                run_id=run_id,
                command=command,
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
            next_status,
            next_sub,
            log_from_status,
            log_to_status,
            log_from_sub,
            log_to_sub,
        )

    def _prepare_scope(
        self, command: LifecycleTransitionCommand
    ) -> tuple[str, str, str, ActorType, str]:
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

        row = lifecycles.get_for_update(lifecycle_id=lifecycle_id)
        if row is None and command.require_lifecycle_row:
            raise LifecycleTransitionError(
                f"workflow_lifecycle not found id={lifecycle_id}"
            )

        current_status, current_sub = self._resolve_current_status(command, row)
        (
            activity_log_id,
            lifecycle_updated,
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

        row = lifecycles.get_for_update(lifecycle_id=lifecycle_id)
        if row is None and first.require_lifecycle_row:
            raise LifecycleTransitionError(
                f"workflow_lifecycle not found id={lifecycle_id}"
            )

        current_status, current_sub = self._resolve_current_status(first, row)

        for command in commands:
            cmd_tenant = resolve_graph_tenant_to_uuid(self._clean(command.tenant_id))
            if cmd_tenant != tenant_uuid:
                raise LifecycleTransitionError(
                    "apply_sequence commands must share tenant_id"
                )
            if (
                self._uuid_or_raise(
                    command.workflow_lifecycle_id,
                    field_name="workflow_lifecycle_id",
                )
                != lifecycle_id
                or self._uuid_or_raise(
                    command.workflow_run_id, field_name="workflow_run_id"
                )
                != run_id
            ):
                raise LifecycleTransitionError(
                    "apply_sequence commands must share "
                    "workflow_lifecycle_id and workflow_run_id"
                )

            step_actor_type = command.actor_type or actor_type
            step_actor_id = self._clean(command.actor_id) or actor_id

            (
                activity_log_id,
                lifecycle_updated,
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
            )
            activity_log_ids.append(activity_log_id)
            if lifecycle_updated:
                any_lifecycle_updated = True

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
