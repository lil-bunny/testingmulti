"""Routing-guide persistence and lifecycle side effects."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.activity_log_descriptions import (
    format_routing_guide_advance_action,
    format_tender_sent_to_vendor,
)
from app.domain.gelita.routing_guide_lifecycle import (
    gelita_current_routing_guide_attempt,
    gelita_has_routing_guide_attempt,
    gelita_routing_guide_sub_status_for,
)
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.load_tendering_state import get_tender, set_tender
from app.domain.load_tendering_settings import is_ftl_load_type, resolve_load_type
from app.models.activity_type import ActivityType, ActorType, is_snapshot_activity_type
from app.models.status import StatusSubType
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def _sync_tender_attempt_in_state(state: Any, *, attempt: int) -> None:
    data = getattr(state, "data", None)
    if not isinstance(data, dict):
        return
    tender = dict(get_tender(data) or {})
    metadata = dict(tender.get("metadata") or {})
    ftl = dict(metadata.get("ftl") or {})
    routing_guide = dict(ftl.get("routing_guide") or {})
    routing_guide["attempt"] = attempt
    ftl["routing_guide"] = routing_guide
    metadata["ftl"] = ftl
    tender["metadata"] = metadata
    set_tender(data, tender)


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
    def record_tenant_sent(self, state: Any) -> bool:
        if not is_ftl_load_type(resolve_load_type(state)):
            return False

        scope = _workflow_scope(state)
        if scope is None:
            logger.warning("routing_guide record_tenant_sent skipped missing scope")
            return False

        wl_id, tenant_id, tender_id, run_id, data = scope
        communication_id = str(data.get("communication_id") or "").strip() or None

        tender = dict(get_tender(data) or {})
        attempt = gelita_current_routing_guide_attempt(tender)
        needs_init = not gelita_has_routing_guide_attempt(tender)
        if needs_init:
            attempt = 1

        to_sub = gelita_routing_guide_sub_status_for(attempt, "tenant")
        transition_meta: dict[str, Any] = {
            "tender_id": tender_id,
            "routing_guide_attempt": attempt,
        }

        def _persist(repos: Any) -> None:
            if needs_init:
                repos.tenders.set_routing_guide_attempt(
                    tenant_id=tenant_id,
                    tender_id=tender_id,
                    attempt=attempt,
                )
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
                    description=format_tender_sent_to_vendor(),
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
        _sync_tender_attempt_in_state(state, attempt=attempt)
        return True

    def advance(self, state: Any, *, reason: str) -> int:
        scope = _workflow_scope(state)
        if scope is None:
            logger.warning("routing_guide advance skipped missing scope")
            tender = get_tender(getattr(state, "data", None) or {})
            return gelita_current_routing_guide_attempt(tender)

        wl_id, tenant_id, tender_id, run_id, data = scope
        tender = dict(get_tender(data) or {})
        prior = gelita_current_routing_guide_attempt(tender)
        next_attempt = prior + 1
        clean_reason = str(reason or "").strip() or "routing_guide_failover"
        transition_meta: dict[str, Any] = {
            "tender_id": tender_id,
            "routing_guide_attempt": next_attempt,
            "routing_guide_reason": clean_reason,
            "prior_attempt": prior,
        }

        def _persist(repos: Any) -> int:
            repos.tenders.set_routing_guide_attempt(
                tenant_id=tenant_id,
                tender_id=tender_id,
                attempt=next_attempt,
            )
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
                    description=format_routing_guide_advance_action(
                        prior_attempt=prior,
                        next_attempt=next_attempt,
                        reason=clean_reason,
                    ),
                    metadata=transition_meta,
                ),
            )
            return next_attempt

        new_attempt = run_with_repos(_persist)
        _sync_tender_attempt_in_state(state, attempt=new_attempt)
        return new_attempt
