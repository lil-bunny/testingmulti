"""Activity log nodes for the ``pod_lifecycle`` workflow."""

from __future__ import annotations

from app.services.pod_lifecycle.pipeline_activity_service import PodPipelineActivityService
from app.services.pod_lifecycle.processed_activity_service import PodProcessedActivityService
from app.services.pod_lifecycle.teams_notification_service import PodLifecycleTeamsNotificationService
from app.services.pod_lifecycle.upload_activity_service import PodUploadActivityService


def record_pod_started_activity(state):
    """Log POD lifecycle started after reminders are scheduled on ``route_completed``."""
    PodPipelineActivityService().record_started_from_state(state)
    return state


def record_pod_reminder_activity(state):
    """After successful POD reminder email: map ``reminder_step`` to lifecycle sub_status."""
    PodPipelineActivityService().record_reminder_from_state(state)
    return state


def record_pod_escalation_activity(state):
    """Log POD escalation sub_status (no email send)."""
    PodPipelineActivityService().record_escalation_from_state(state)
    return state


def record_pod_upload_activity(state):
    """Log POD S3 upload outcome after in-graph merge_and_upload_pod_attachments."""
    PodUploadActivityService().record_from_state(state)
    return state


def record_pod_extraction_activity(state):
    """Log POD LLM extraction outcome after ``pod_analysis``."""
    PodPipelineActivityService().record_extraction_from_state(state)
    return state


def record_pod_vs_ratecon_activity(state):
    """Log POD vs ratecon validation outcome after ``pod_vs_ratecon_analysis``."""
    PodPipelineActivityService().record_vs_ratecon_from_state(state)
    return state


def record_pod_processed_activity(state):
    """Finalize POD processing after LLM/ratecon."""
    PodProcessedActivityService().record_from_state(state)
    return state


def notify_pod_analysis_teams(state):
    """Post POD analysis summary to Teams (tenant-configured webhook)."""
    result = PodLifecycleTeamsNotificationService().notify_from_state(state)
    state.data["pod_teams_notification_sent"] = result.sent
    if result.skip_reason:
        state.data["pod_teams_notification_skipped"] = result.skip_reason
    if result.error:
        state.data["pod_teams_notification_error"] = result.error
    return state
