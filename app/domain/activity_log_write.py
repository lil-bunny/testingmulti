"""DTOs for ``ActivityLogService`` writes (column-shaped, pass-through to lifecycle layer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType


@dataclass(frozen=True)
class ActivityLogWrite:
    """Scope + payload for a single ``activity_logs`` row."""

    tenant_id: str
    workflow_lifecycle_id: str
    workflow_run_id: str

    description: str | None = None
    metadata: dict[str, Any] | None = None
    communication_id: str | None = None
    actor_type: ActorType | None = ActorType.SYSTEM
    actor_id: str | None = None

    to_status: StatusType | None = None
    to_sub_status: StatusSubType | None = None
    from_status: StatusType | None = None
    from_sub_status: StatusSubType | None = None

    update_lifecycle: bool = True
    record_log: bool = True
    email_thread_id: str | None = None
    require_lifecycle_row: bool = True


@dataclass(frozen=True)
class ActivityLogStep:
    """One step in ``record_sequence`` (sets ``activity_type`` explicitly)."""

    activity_type: ActivityType
    description: str | None = None
    metadata: dict[str, Any] | None = None
    communication_id: str | None = None

    to_status: StatusType | None = None
    to_sub_status: StatusSubType | None = None
    from_status: StatusType | None = None
    from_sub_status: StatusSubType | None = None

    update_lifecycle: bool | None = None
    record_log: bool = True


@dataclass(frozen=True)
class ActivityLogSequence:
    """Multiple log rows (+ optional lifecycle updates) in one transaction."""

    tenant_id: str
    workflow_lifecycle_id: str
    workflow_run_id: str
    steps: tuple[ActivityLogStep, ...]

    actor_type: ActorType | None = ActorType.SYSTEM
    actor_id: str | None = None
    email_thread_id: str | None = None
    require_lifecycle_row: bool = True


@dataclass(frozen=True)
class ActivityLogSequenceResult:
    """Outcome of ``record_sequence`` / ``apply_sequence``."""

    activity_log_ids: list[str | None] = field(default_factory=list)
    lifecycle_updated: bool = False
