"""Multi-stop POD lifecycle nodes.

Temporary nodes for multi-stop shipments that skip extraction/scoring
but still record needs_action and notify Teams. These will be removed
once multi-stop scoring logic is implemented.
"""

from __future__ import annotations

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.pod_lifecycle.guards import (
    pod_upload_success_from_state,
    should_skip_idempotent_pod_activity_log,
)
from app.domain.pod_lifecycle.teams_notification import (
    parse_pod_teams_notification_settings,
    resolve_pod_analysis_load_id,
)
from app.domain.status_parsing import status_type_from_db
from app.integrations.teams.webhook import TeamsWebhookError, post_message_card
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)

_MULTI_STOP_DONE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_UPLOADED.value,
        StatusSubType.DOCUMENT_PROCESSED.value,
        StatusSubType.UPLOADED_TO_TMS.value,
    }
)

_MULTI_STOP_NOTIFY_EVENTS = frozenset(
    {
        WorkflowRunEventType.EMAIL_RECEIVED.value,
        WorkflowRunEventType.MANUAL_POD_UPLOAD.value,
    }
)


def record_multi_stop_pod_activity(state):
    """Transition multi-stop POD to pending_review / document_uploaded (needs manual review)."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "record_multi_stop_pod_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    if not pod_upload_success_from_state(state.data):
        return state

    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)

    if should_skip_idempotent_pod_activity_log(
        state.data,
        row,
        done_sub_statuses=_MULTI_STOP_DONE_SUB_STATUSES,
    ):
        logger.info(
            "record_multi_stop_pod_activity skipping already processed lifecycle_id=%s",
            wl_id,
        )
        return state

    current_status = status_type_from_db(row.get("status")) if row else None
    to_status = StatusType.PENDING_REVIEW

    if current_status == to_status:
        step = ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
            metadata=None,
        )
    else:
        step = ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=StatusSubType.DOCUMENT_UPLOADED,
            metadata=None,
        )

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(step,),
        )
    )
    return state


def notify_multi_stop_pod_teams(state):
    """Post a Teams card for multi-stop POD upload (needs manual review, no scoring)."""
    data = state.data
    tenant_settings = data.get("tenant_settings")
    if not isinstance(tenant_settings, dict):
        tenant_settings = {}

    settings = parse_pod_teams_notification_settings(tenant_settings)
    if settings is None:
        state.data["pod_teams_notification_sent"] = False
        state.data["pod_teams_notification_skipped"] = "no_teams_notification_settings"
        return state

    event_type = str(data.get("event_type") or "").strip()
    if event_type not in _MULTI_STOP_NOTIFY_EVENTS:
        state.data["pod_teams_notification_sent"] = False
        state.data["pod_teams_notification_skipped"] = "not_pod_analysis_event"
        return state

    if not pod_upload_success_from_state(data):
        state.data["pod_teams_notification_sent"] = False
        state.data["pod_teams_notification_skipped"] = "pod_upload_not_succeeded"
        return state

    load_id = resolve_pod_analysis_load_id(data)
    if not load_id:
        state.data["pod_teams_notification_sent"] = False
        state.data["pod_teams_notification_skipped"] = "missing_load_id"
        return state

    title = f"Multi-stop POD uploaded — Load {load_id}"
    body = (
        f"Load {load_id} is a multi-stop shipment. "
        "POD has been uploaded but extraction and scoring were skipped. "
        "Manual review required."
    )
    facts = [
        ("Load ID", load_id),
        ("Status", "NEEDS MANUAL REVIEW"),
        ("Reason", "Multi-stop shipment — automated scoring not supported"),
    ]

    wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
    try:
        run_sync(
            post_message_card(
                settings.teams_webhook_url,
                title=title,
                text=body,
                facts=facts,
            )
        )
    except TeamsWebhookError as exc:
        logger.warning(
            "multi-stop pod Teams post failed lifecycle_id=%s status=%s",
            wl_id,
            exc.status_code,
        )
        state.data["pod_teams_notification_sent"] = False
        state.data["pod_teams_notification_error"] = "teams_post_failed"
        return state

    logger.info(
        "multi-stop pod Teams notification sent lifecycle_id=%s load_id=%s",
        wl_id,
        load_id,
    )
    state.data["pod_teams_notification_sent"] = True
    return state
