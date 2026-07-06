"""Routing-guide persistence and lifecycle side effects."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.activity_log_descriptions import format_tender_sent_to_tenant
from app.domain.gelita.routing_guide_lifecycle import (
    mark_routing_guide_reminders_scheduled_for_attempt,
    routing_guide_attempt_from_metadata,
    routing_guide_attempt_from_state,
    routing_guide_has_attempt,
    gelita_routing_guide_sub_status_for,
    sync_routing_guide_attempt_to_state,
)
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.load_tendering_settings import (
    is_ftl_load_type,
    resolve_load_type,
    routing_guide_max_attempts,
)
from app.models.activity_type import ActivityType, ActorType, is_snapshot_activity_type
from app.models.status import StatusSubType
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService

logger = get_logger(__name__)


def _lifecycle_command(
    *,
    tenant_id: str,
    workflow_lifecycle_id: str,
    workflow_run_id: str,
    activity_type: ActivityType,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    to_sub_status: StatusSubType | None = None,
    communication_id: str | None = None,
) -> LifecycleTransitionCommand:
    """Build a system lifecycle transition for routing-guide activity logging."""
    return LifecycleTransitionCommand(
        tenant_id=tenant_id,
        workflow_lifecycle_id=workflow_lifecycle_id,
        workflow_run_id=workflow_run_id,
        activity_type=activity_type,
        description=description,
        metadata=metadata or {},
        actor_type=ActorType.SYSTEM,
        to_sub_status=to_sub_status,
        update_lifecycle=not is_snapshot_activity_type(activity_type),
        communication_id=communication_id,
    )


def _workflow_scope(state: Any) -> tuple[str, str, str, str, dict[str, Any]] | None:
    """Extract lifecycle scope ids from graph state; required by persist helpers."""
    data = getattr(state, "data", None) or {}
    wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = str(
        getattr(state, "tenant_id", None) or data.get("tenant_id") or ""
    ).strip()
    tender_id = str(data.get("tender_id") or "").strip()
    run_id = str(getattr(state, "execution_id", None) or "").strip()
    if not wl_id or not tenant_id or not tender_id or not run_id:
        return None
    return wl_id, tenant_id, tender_id, run_id, data


class RoutingGuideLifecycleService:
    """Persist routing-guide attempt counters and lifecycle sub-status transitions."""

    def record_tenant_sent(self, state: Any) -> bool:
        """Initialize or reaffirm attempt 1 when the tenant email is sent."""
        if not is_ftl_load_type(resolve_load_type(state)):
            return False

        scope = _workflow_scope(state)
        if scope is None:
            logger.warning("routing_guide record_tenant_sent skipped missing scope")
            return False

        wl_id, tenant_id, tender_id, run_id, data = scope
        communication_id = str(data.get("communication_id") or "").strip() or None

        attempt = routing_guide_attempt_from_state(data)

        def _persist(repos: Any) -> None:
            nonlocal attempt
            lifecycle_row = repos.workflow_lifecycles.read_row_by_id(wl_id)
            lifecycle_meta = (
                lifecycle_row.get("metadata") if isinstance(lifecycle_row, dict) else {}
            )
            needs_init = not routing_guide_has_attempt(lifecycle_meta)
            if needs_init:
                attempt = 1
                if not repos.workflow_lifecycles.set_routing_guide_attempt(
                    lifecycle_id=wl_id,
                    attempt=attempt,
                ):
                    logger.warning(
                        "routing_guide record_tenant_sent failed to persist attempt "
                        "workflow_lifecycle_id=%s attempt=%s",
                        wl_id,
                        attempt,
                    )
            else:
                attempt = routing_guide_attempt_from_metadata(lifecycle_meta)

            to_sub = gelita_routing_guide_sub_status_for(attempt, "tenant")
            transition_meta: dict[str, Any] = {
                "tender_id": tender_id,
                "routing_guide_attempt": attempt,
            }

            lifecycle_transition_service = LifecycleTransitionService(
                lifecycles_repo=repos.workflow_lifecycles,
                activity_logs_repo=repos.activity_logs,
            )
            lifecycle_transition_service.apply_sequence(
                _lifecycle_command(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    activity_type=ActivityType.ACTION,
                    description=format_tender_sent_to_tenant(),
                    metadata=transition_meta,
                    communication_id=communication_id,
                ),
                _lifecycle_command(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    activity_type=ActivityType.SUB_STATUS_CHANGE,
                    metadata=transition_meta,
                    to_sub_status=to_sub,
                ),
            )

        run_with_repos(_persist)
        sync_routing_guide_attempt_to_state(data, attempt=attempt)
        return True

    def mark_reminders_scheduled_for_attempt(self, state: Any, *, attempt: int) -> bool:
        """Persist per-attempt reminder schedule idempotency on lifecycle metadata."""
        scope = _workflow_scope(state)
        if scope is None:
            return False
        wl_id, _tenant_id, _tender_id, _run_id, data = scope
        patch = mark_routing_guide_reminders_scheduled_for_attempt(attempt=attempt)

        def _persist(repos: Any) -> bool:
            return repos.workflow_lifecycles.patch_metadata(
                lifecycle_id=wl_id,
                metadata_patch=patch,
            )

        if not run_with_repos(_persist):
            return False
        lifecycle_meta = data.get("workflow_lifecycle_metadata")
        if not isinstance(lifecycle_meta, dict):
            lifecycle_meta = {}
            data["workflow_lifecycle_metadata"] = lifecycle_meta
        lifecycle_meta.update(patch)
        return True

    def advance(self, state: Any, *, reason: str) -> int:
        """Increment waterfall attempt after carrier reject or timeout."""
        scope = _workflow_scope(state)
        if scope is None:
            logger.warning("routing_guide advance skipped missing scope")
            return routing_guide_attempt_from_state(getattr(state, "data", None))

        wl_id, tenant_id, tender_id, run_id, data = scope
        state_prior = routing_guide_attempt_from_state(data)
        max_attempts = routing_guide_max_attempts(state)

        reminder_cancel_service = WorkflowReminderCancelService()
        reminder_cancel_service.cancel_for_attempt(
            lifecycle_id=wl_id,
            attempt=state_prior,
        )

        def _persist(repos: Any) -> int:
            lifecycle_row = repos.workflow_lifecycles.read_row_by_id(wl_id)
            lifecycle_meta = (
                lifecycle_row.get("metadata") if isinstance(lifecycle_row, dict) else {}
            )
            live = routing_guide_attempt_from_metadata(lifecycle_meta)
            if live > state_prior:
                return live
            if live >= max_attempts:
                return live
            prior = max(live, state_prior)
            next_attempt = prior + 1
            if not repos.workflow_lifecycles.set_routing_guide_attempt(
                lifecycle_id=wl_id,
                attempt=next_attempt,
            ):
                logger.warning(
                    "routing_guide advance failed to persist attempt "
                    "workflow_lifecycle_id=%s attempt=%s",
                    wl_id,
                    next_attempt,
                )
            return next_attempt

        new_attempt = run_with_repos(_persist)
        sync_routing_guide_attempt_to_state(data, attempt=new_attempt)
        return new_attempt
