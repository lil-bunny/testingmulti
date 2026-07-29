"""Post appointment scheduling draft-ready notification to Teams."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logger import get_logger
from app.domain.appointment_scheduling.teams_notification import (
    display_fields_from_data,
    draft_ready_facts,
    format_draft_ready_body,
    format_draft_ready_title,
    parse_appointment_scheduling_teams_notification_settings,
)
from app.domain.state import WorkflowState
from app.integrations.teams.webhook import TeamsWebhookError, post_message_card_sync
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class TeamsNotificationResult:
    sent: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None


class TeamsNotificationService:
    def __init__(
        self,
        *,
        activity_service: ActivityService | None = None,
    ) -> None:
        self._activity = activity_service or ActivityService()

    def notify_from_state(self, state: WorkflowState) -> TeamsNotificationResult:
        data = state.data
        tenant_settings = data.get("tenant_settings")
        if not isinstance(tenant_settings, dict):
            tenant_settings = {}

        settings = parse_appointment_scheduling_teams_notification_settings(tenant_settings)
        if settings is None:
            return TeamsNotificationResult(
                skipped=True,
                skip_reason="no_teams_notification_settings",
            )

        event_type = str(data.get("event_type") or "").strip()
        if event_type != WorkflowRunEventType.TURVO_PICKUP_CHANGED.value:
            return TeamsNotificationResult(
                skipped=True,
                skip_reason="not_intake_event",
            )

        fields = display_fields_from_data(data)
        if fields is None:
            return TeamsNotificationResult(
                skipped=True,
                skip_reason="draft_not_ready",
            )

        title = format_draft_ready_title(settings.message_title, fields=fields)
        body = format_draft_ready_body(settings.message_body, fields=fields)
        facts = draft_ready_facts(fields)

        wl_id = fields.workflow_lifecycle_id
        try:
            post_message_card_sync(
                settings.teams_webhook_url,
                title=title,
                text=body,
                facts=facts,
            )
        except TeamsWebhookError as exc:
            logger.warning(
                "appointment scheduling Teams post failed lifecycle_id=%s status=%s",
                wl_id,
                exc.status_code,
            )
            return TeamsNotificationResult(error="teams_post_failed")

        self._activity.record_draft_teams_notification(state)
        logger.info(
            "appointment scheduling Teams notification sent lifecycle_id=%s load_id=%s",
            wl_id,
            fields.load_id,
        )
        return TeamsNotificationResult(sent=True)


__all__ = (
    "TeamsNotificationResult",
    "TeamsNotificationService",
)
