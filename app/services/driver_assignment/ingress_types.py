"""Driver assignment ingress constants and result types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.status import StatusSubType

DRIVER_ASSIGNMENT_WORKFLOW = "driver_assignment"
RATECON_WORKFLOW = "ratecon"

DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML = (
    "<html><body>"
    "<p>Thanks for your reply.</p>"
    "<p>We still need <strong>complete driver details</strong> for this load.</p>"
    "<p>Please reply with the driver&apos;s <strong>full name</strong> and "
    "<strong>mobile number</strong> (or email address).</p>"
    "<p>If you already sent this, please reply again with both in one message.</p>"
    "</body></html>"
)

PREPARE_REQUIRED_KEYS = (
    "load_id",
    "shipments_row_id",
    "shipment_id",
    "ratecon_workflow_lifecycle_id",
)

LAYER1_ACTIVITY_SKIP_REASONS = frozenset(
    {
        "pickup_appointment_not_found",
        "driver_already_assigned",
        "shipment_not_in_state",
        "transportation_mode_not_tl",
        "shipment_not_covered",
        "excluded_carrier",
    }
)

DRIVER_DETAILS_TERMINAL_SUB_STATUSES = frozenset(
    {
        StatusSubType.DETAILS_RECEIVED,
        StatusSubType.DRIVER_DETAILS_EMAIL_RECEIVED,
        StatusSubType.UPLOADED_TO_TMS,
        StatusSubType.CANCELLED,
    }
)


@dataclass(frozen=True)
class EnqueueResult:
    enqueued: bool
    skip_reason: str | None = None
    execution_id: str | None = None
    celery_task_id: str | None = None


@dataclass(frozen=True)
class PrepareResult:
    skipped: bool
    skip_reason: str | None = None
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class EligibilityResult:
    skip_reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.skip_reason is None


@dataclass(frozen=True)
class SendReminderResult:
    sent: bool
    error: str | None = None
    communication_id: str | None = None
    reminder_step: int | None = None
    skip_sub_status_bump: bool = False
