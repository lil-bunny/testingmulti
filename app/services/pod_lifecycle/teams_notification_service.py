"""Post POD analysis summary to Teams after successful processing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle.guards import pod_upload_success_from_state
from app.domain.pod_lifecycle.teams_notification import (
    format_pod_analysis_body,
    format_pod_analysis_title,
    parse_pod_teams_notification_settings,
    pod_analysis_display_fields_from_data,
    pod_analysis_facts,
    resolve_pod_analysis_load_id,
)
from app.domain.state import WorkflowState
from app.integrations.teams.webhook import TeamsWebhookError, post_message_card
from app.models.workflow_run_event_type import WorkflowRunEventType

logger = get_logger(__name__)

_POD_ANALYSIS_NOTIFY_EVENTS = frozenset(
    {
        WorkflowRunEventType.EMAIL_RECEIVED.value,
        WorkflowRunEventType.MANUAL_POD_UPLOAD.value,
    }
)


@dataclass(frozen=True)
class PodTeamsNotificationResult:
    sent: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None


class PodLifecycleTeamsNotificationService:
    def notify_from_state(self, state: WorkflowState) -> PodTeamsNotificationResult:
        data = state.data
        tenant_settings = data.get("tenant_settings")
        if not isinstance(tenant_settings, dict):
            tenant_settings = {}

        settings = parse_pod_teams_notification_settings(tenant_settings)
        if settings is None:
            return PodTeamsNotificationResult(skipped=True, skip_reason="no_teams_notification_settings")

        event_type = str(data.get("event_type") or "").strip()
        if event_type not in _POD_ANALYSIS_NOTIFY_EVENTS:
            return PodTeamsNotificationResult(skipped=True, skip_reason="not_pod_analysis_event")

        if not pod_upload_success_from_state(data):
            return PodTeamsNotificationResult(skipped=True, skip_reason="pod_upload_not_succeeded")

        if not _analysis_success(data):
            return PodTeamsNotificationResult(skipped=True, skip_reason="pod_analysis_not_stored")

        vs_results = data.get("pod_vs_ratecon_analysis_results")
        if not isinstance(vs_results, dict):
            return PodTeamsNotificationResult(
                skipped=True, skip_reason="missing_vs_ratecon_results"
            )

        fields = pod_analysis_display_fields_from_data(data)
        if fields is None:
            skip_reason = _display_fields_skip_reason(data, vs_results)
            return PodTeamsNotificationResult(skipped=True, skip_reason=skip_reason)

        title = format_pod_analysis_title(settings.message_title, fields=fields)
        body = format_pod_analysis_body(settings.message_body, fields=fields)
        facts = pod_analysis_facts(fields)

        wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
        # ponytail: Teams stays live in workflow shadow_mode (email/Turvo are gated elsewhere)
        try:
            asyncio.run(
                post_message_card(
                    settings.teams_webhook_url,
                    title=title,
                    text=body,
                    facts=facts,
                )
            )
        except TeamsWebhookError as exc:
            logger.warning(
                "pod analysis Teams post failed lifecycle_id=%s status=%s",
                wl_id,
                exc.status_code,
            )
            return PodTeamsNotificationResult(error="teams_post_failed")

        logger.info(
            "pod analysis Teams notification sent lifecycle_id=%s load_id=%s",
            wl_id,
            fields.load_id,
        )
        return PodTeamsNotificationResult(sent=True)


def _analysis_success(data: dict[str, Any]) -> bool:
    persist = data.get("document_analysis_pod")
    return isinstance(persist, dict) and persist.get("stored") is True


def _display_fields_skip_reason(data: dict[str, Any], vs_results: dict[str, Any]) -> str:
    if vs_results.get("confidence_score") is None:
        return "missing_confidence_score"
    if not str(vs_results.get("validation_summary") or "").strip():
        return "missing_validation_summary"
    if not resolve_pod_analysis_load_id(data):
        return "missing_load_id"
    return "missing_display_fields"
