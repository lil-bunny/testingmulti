"""Human-readable ``activity_logs.description`` strings."""

from __future__ import annotations

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType

_STATUS_CHANGE_TEMPLATE = "Status changed from {from_status} to {to_status}"
_SUB_STATUS_CHANGE_TEMPLATE = (
    "Sub-status changed from {from_sub_status} to {to_sub_status}"
)


def _label_status(value: StatusType) -> str:
    if value == StatusType.NONE:
        return "None"
    return value.value.replace("_", " ").title()


def _label_sub_status(value: StatusSubType) -> str:
    if value == StatusSubType.NONE:
        return "None"
    return value.value.replace("_", " ").title()


def generate_activity_log_description(
    *,
    activity_type: ActivityType,
    from_status: StatusType,
    to_status: StatusType,
    from_sub_status: StatusSubType,
    to_sub_status: StatusSubType,
) -> str | None:
    """
    Build a transition description from templates.

    ``STATUS_CHANGE``: status line only (sub-status columns may still differ).
    ``SUB_STATUS_CHANGE``: sub-status line only.
    ``ACTION``: no template — callers supply narrative text.
    """
    if activity_type == ActivityType.STATUS_CHANGE:
        if from_status == to_status:
            return None
        return _STATUS_CHANGE_TEMPLATE.format(
            from_status=_label_status(from_status),
            to_status=_label_status(to_status),
        )
    if activity_type == ActivityType.SUB_STATUS_CHANGE:
        if from_sub_status == to_sub_status:
            return None
        return _SUB_STATUS_CHANGE_TEMPLATE.format(
            from_sub_status=_label_sub_status(from_sub_status),
            to_sub_status=_label_sub_status(to_sub_status),
        )
    return None


def format_tender_created_action(
    *,
    tender_id: str,
    order_number: str,
    customer_name: str,
) -> str:
    order = (order_number or "").strip() or tender_id
    customer = (customer_name or "").strip() or "Unknown"
    return f"Tender {order} created for {customer}"


def format_tender_sent_to_vendor() -> str:
    return "Tender email sent to vendor"


def format_carrier_ack_llm_action(
    *,
    decision: str,
    reason: str,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    reason_s = (reason or "").strip() or "no reason"
    return f"Carrier ack LLM classified reply as {decision}{conf}: {reason_s}"
