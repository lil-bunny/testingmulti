"""Command and result types for atomic lifecycle status + activity log writes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType


def _normalize_uuid(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return str(uuid.UUID(s))
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class LifecycleTransitionCommand:
    """One business transition: optional lifecycle update + optional activity log."""

    tenant_id: str
    workflow_lifecycle_id: str
    workflow_run_id: str
    activity_type: ActivityType

    to_status: StatusType | None = None
    to_sub_status: StatusSubType | None = None

    description: str | None = None
    metadata: dict[str, Any] | None = None
    communication_id: str | None = None

    actor_type: ActorType | None = None
    actor_id: str | None = None

    from_status: StatusType | None = None
    from_sub_status: StatusSubType | None = None

    update_lifecycle: bool = True
    record_activity: bool = True
    require_lifecycle_row: bool = True

    email_thread_id: str | None = None

    @classmethod
    def from_workflow_state(
        cls,
        state: Any,
        *,
        activity_type: ActivityType,
        to_status: StatusType | None = None,
        to_sub_status: StatusSubType | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor_type: ActorType | None = None,
        actor_id: str | None = None,
        from_status: StatusType | None = None,
        from_sub_status: StatusSubType | None = None,
        update_lifecycle: bool = True,
        record_activity: bool = True,
        require_lifecycle_row: bool = True,
        email_thread_id: str | None = None,
        communication_id: str | None = None,
        workflow_lifecycle_id: str | None = None,
        workflow_run_id: str | None = None,
        tenant_id: str | None = None,
    ) -> LifecycleTransitionCommand:
        data = getattr(state, "data", None) or {}
        tenant_raw = tenant_id
        if tenant_raw is None:
            tenant_raw = data.get("tenant_id") if isinstance(data, dict) else None
        if tenant_raw is None:
            tenant_raw = getattr(state, "tenant_id", None)

        wl = workflow_lifecycle_id
        if wl is None and isinstance(data, dict):
            wl = data.get("workflow_lifecycle_id")

        wr = workflow_run_id
        if wr is None:
            wr = getattr(state, "execution_id", None)

        thread = email_thread_id
        if thread is None and isinstance(data, dict):
            thread = data.get("thread_id") or data.get("email_thread_id")

        comm = communication_id
        if comm is None and isinstance(data, dict):
            comm = data.get("communication_id")

        return cls(
            tenant_id=str(tenant_raw or "").strip(),
            workflow_lifecycle_id=str(wl or "").strip(),
            workflow_run_id=str(wr or "").strip(),
            activity_type=activity_type,
            to_status=to_status,
            to_sub_status=to_sub_status,
            description=description,
            metadata=metadata,
            actor_type=actor_type,
            actor_id=actor_id,
            from_status=from_status,
            from_sub_status=from_sub_status,
            update_lifecycle=update_lifecycle,
            record_activity=record_activity,
            require_lifecycle_row=require_lifecycle_row,
            email_thread_id=str(thread).strip() if thread else None,
            communication_id=_normalize_uuid(comm),
        )


@dataclass(frozen=True)
class LifecycleTransitionResult:
    lifecycle_updated: bool
    activity_log_id: str | None
    from_status: StatusType | None
    from_sub_status: StatusSubType | None
    to_status: StatusType | None
    to_sub_status: StatusSubType | None


@dataclass(frozen=True)
class LifecycleTransitionSequenceResult:
    """Multiple activity log inserts (and lifecycle updates) in one transaction."""

    activity_log_ids: list[str | None]
    lifecycle_updated: bool


class LifecycleTransitionError(Exception):
    """Raised when a strict lifecycle transition cannot be applied."""
