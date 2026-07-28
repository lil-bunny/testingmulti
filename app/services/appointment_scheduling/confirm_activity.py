"""Confirm-phase activity logs for appointment scheduling."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_email_sent_action,
    format_ascend_pickup_updated_action,
    format_turvo_delivery_placeholder_action,
    format_turvo_pickup_updated_action,
)
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActorType
from app.models.status import StatusSubType
from app.services.appointment_scheduling.activity_common import (
    SchedulingActivityDeps,
    build_sub_status_transition_command,
    scope_ids,
)


class ConfirmActivity:
    def __init__(self, deps: SchedulingActivityDeps) -> None:
        self._deps = deps

    def record_confirm_email_sent(
        self,
        state,
        *,
        communication_id: str | None,
        actor_id: str | None,
    ) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        wl_id, _, _ = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
        current_sub = sub_status_type_from_db(row.get("sub_status")) if row else None
        if current_sub == StatusSubType.AWAITING_CUSTOMER_REPLY:
            return

        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_appointment_email_sent_action(),
                communication_id=communication_id,
                actor_type=ActorType.USER,
                actor_id=actor_id,
            )
        )

    def record_awaiting_customer_reply(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
        current_status = status_type_from_db(row.get("status")) if row else None
        current_sub = sub_status_type_from_db(row.get("sub_status")) if row else None
        if current_sub == StatusSubType.AWAITING_CUSTOMER_REPLY:
            return

        self._deps.apply(
            build_sub_status_transition_command(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                current_status=current_status,
                new_sub=StatusSubType.AWAITING_CUSTOMER_REPLY,
            )
        )

    def record_weekend_pickup_update(self, state, *, result: dict[str, Any]) -> None:
        if not isinstance(result, dict) or result.get("skipped"):
            return
        scope = scope_ids(state)
        if scope is None:
            return

        data = getattr(state, "data", None) or {}
        commands: list[LifecycleTransitionCommand] = []
        if result.get("ascend_updated"):
            commands.append(
                self._deps.action_from_state(
                    state,
                    description=format_ascend_pickup_updated_action(
                        reference_number=str(data.get("reference_number") or ""),
                        start_time=str(result.get("turvo_pickup_start_time") or ""),
                    ),
                )
            )
        if result.get("turvo_updated"):
            commands.append(
                self._deps.action_from_state(
                    state,
                    description=format_turvo_pickup_updated_action(
                        stop_name=str(result.get("pickup_stop_name") or ""),
                        start_time=str(result.get("turvo_pickup_start_time") or ""),
                    ),
                )
            )
        if commands:
            self._deps.apply_sequence(*commands)

    def record_turvo_confirm_placeholder(self, state, *, result: dict[str, Any]) -> None:
        if scope_ids(state) is None or not isinstance(result, dict):
            return
        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_turvo_delivery_placeholder_action(
                    stop_name=str(result.get("stop_name") or ""),
                    start_time=str(result.get("start_time") or ""),
                ),
            )
        )
