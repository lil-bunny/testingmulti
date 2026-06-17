"""Deliver workflow error alerts per tenant ``workflow_error_alerts`` settings."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_workflow_error_alert_sent_action
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.load_tendering_settings import shared_unipile_account_settings
from app.domain.tenant_settings.workflow_error_alerts import (
    WorkflowErrorAlertChannelSettings,
    WorkflowErrorAlertEmailChannelSettings,
)
from app.domain.workflow_error_alert_payload import WorkflowErrorAlertPayload
from app.domain.workflow_error_alert_settings import resolve_workflow_error_alert_settings
from app.domain.workflow_error_alert_templates import (
    build_workflow_error_alert_template_context,
    format_workflow_error_alert_template,
)
from app.models.communication_channel_enum import CommunicationChannel
from app.services.activity_log_service import ActivityLogService
from app.services.communications.service import CommunicationsService
from app.services.unipile_service import UnipileException
from app.tools.email import send_email

logger = get_logger(__name__)

_ALERT_SOURCE = "workflow_error_alert"


class WorkflowErrorAlertDeliveryError(Exception):
    """Raised when one or more configured alert channels fail after retries."""


def _idempotency_key(
    *,
    tenant_id: str,
    workflow_lifecycle_id: str,
    workflow_run_id: str,
    error_code: str,
    channel: str,
) -> str:
    """Stable dedupe key for one failure event on a single communication channel."""
    return ":".join(
        [
            tenant_id.strip(),
            workflow_lifecycle_id.strip(),
            workflow_run_id.strip(),
            error_code.strip(),
            channel.strip(),
        ]
    )


class WorkflowErrorAlertService:
    """Fan out workflow error alerts to configured communication channels."""

    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
        activity_log_service: ActivityLogService | None = None,
    ) -> None:
        self._communications_service = communications_service or CommunicationsService()
        self._activity_log_service = activity_log_service or ActivityLogService()

    def send_workflow_error_alert(self, payload: WorkflowErrorAlertPayload) -> None:
        """
        Deliver alerts for one catalog error.

        Resolves per-workflow alert settings, renders templates, sends on each
        enabled channel, persists communications, and records activity log actions.
        Raises when any channel fails so the worker can retry.
        """
        settings = resolve_workflow_error_alert_settings(
            {"tenant_settings": payload.tenant_settings},
            workflow_name=payload.workflow_name,
        )
        if settings is None:
            logger.info(
                "workflow_error_alert skipped: no enabled settings tenant_id=%s workflow=%s",
                payload.tenant_id,
                payload.workflow_name,
            )
            return

        error_code = str(payload.error.get("code") or "").strip()
        template_context = build_workflow_error_alert_template_context(
            data=payload.workflow_data,
            error=payload.error,
            workflow_lifecycle_id=payload.workflow_lifecycle_id,
            workflow_run_id=payload.workflow_run_id,
        )

        failures: list[str] = []
        for channel_cfg in settings.channels:
            channel = channel_cfg.channel
            try:
                self._deliver_channel(
                    payload=payload,
                    channel_cfg=channel_cfg,
                    error_code=error_code,
                    template_context=template_context,
                )
            except Exception:
                logger.exception(
                    "workflow_error_alert channel failed tenant_id=%s channel=%s error_code=%s",
                    payload.tenant_id,
                    channel,
                    error_code,
                )
                failures.append(channel)

        if failures:
            raise WorkflowErrorAlertDeliveryError(
                f"workflow error alert failed for channels: {', '.join(failures)}"
            )

    def _deliver_channel(
        self,
        *,
        payload: WorkflowErrorAlertPayload,
        channel_cfg: WorkflowErrorAlertChannelSettings,
        error_code: str,
        template_context: dict[str, str],
    ) -> None:
        """Send on one channel when not already delivered for this run and error code."""
        channel = channel_cfg.channel
        idempotency_key = _idempotency_key(
            tenant_id=payload.tenant_id,
            workflow_lifecycle_id=payload.workflow_lifecycle_id,
            workflow_run_id=payload.workflow_run_id,
            error_code=error_code,
            channel=channel,
        )
        if self._communications_service.find_outbound_id_by_idempotency_key(
            tenant_id=payload.tenant_id,
            idempotency_key=idempotency_key,
            channel=channel,
        ):
            return

        if isinstance(channel_cfg, WorkflowErrorAlertEmailChannelSettings):
            communication_id = self._send_email_channel(
                payload=payload,
                channel_cfg=channel_cfg,
                idempotency_key=idempotency_key,
                template_context=template_context,
            )
        else:
            logger.info(
                "workflow_error_alert channel not implemented channel=%s tenant_id=%s",
                channel,
                payload.tenant_id,
            )
            return

        if communication_id:
            self._record_alert_action(
                payload=payload,
                channel=channel,
                communication_id=communication_id,
                error_code=error_code,
            )

    def _send_email_channel(
        self,
        *,
        payload: WorkflowErrorAlertPayload,
        channel_cfg: WorkflowErrorAlertEmailChannelSettings,
        idempotency_key: str,
        template_context: dict[str, str],
    ) -> str | None:
        """Render templates, send outbound email, and return the communications row id."""
        account_id = self._resolve_sender_account_id(payload)
        if not account_id:
            raise UnipileException("workflow_error_alert: missing sender account_id")

        subject = format_workflow_error_alert_template(channel_cfg.subject, template_context)
        body = format_workflow_error_alert_template(channel_cfg.body_template, template_context)
        metadata = self._alert_communication_metadata(
            payload=payload,
            channel=CommunicationChannel.EMAIL.value,
            idempotency_key=idempotency_key,
        )
        result = send_email(
            to=channel_cfg.to,
            cc=channel_cfg.cc,
            bcc=channel_cfg.bcc,
            subject=subject,
            body=body,
            account_id=account_id,
            tenant_id=payload.tenant_id,
            communication_metadata=metadata,
            workflow_run_id=payload.workflow_run_id,
        )
        if not result or not result.get("success"):
            raise UnipileException("workflow_error_alert: email send failed")
        comm_id = result.get("communication_id")
        return str(comm_id).strip() if comm_id else None

    @staticmethod
    def _resolve_sender_account_id(payload: WorkflowErrorAlertPayload) -> str:
        """Outbound email provider account id from the workflow tenant settings blob."""
        merged = shared_unipile_account_settings(
            {"tenant_settings": payload.tenant_settings}
        )
        return str(merged.get("ana_at_gelita_account_id") or "").strip()

    @staticmethod
    def _alert_communication_metadata(
        *,
        payload: WorkflowErrorAlertPayload,
        channel: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Metadata stored on the outbound communications row for audit and dedupe."""
        meta: dict[str, Any] = {
            "source": _ALERT_SOURCE,
            "alert_type": _ALERT_SOURCE,
            "channel": channel,
            "idempotency_key": idempotency_key,
            "error_code": payload.error.get("code"),
            "error_category": payload.error.get("category"),
            "workflow_lifecycle_id": payload.workflow_lifecycle_id,
            "workflow_name": payload.workflow_name,
        }
        if payload.tender_id:
            meta["tender_id"] = payload.tender_id
        if payload.pack_code:
            meta["pack_code"] = payload.pack_code
        if payload.delivery_address_code:
            meta["delivery_address_code"] = payload.delivery_address_code
        return meta

    def _record_alert_action(
        self,
        *,
        payload: WorkflowErrorAlertPayload,
        channel: str,
        communication_id: str,
        error_code: str,
    ) -> None:
        """Append one activity log action linked to the outbound communication."""
        metadata: dict[str, Any] = {
            "error_code": error_code,
            "error_category": payload.error.get("category"),
            "channel": channel,
            "alert_type": _ALERT_SOURCE,
        }
        if payload.tender_id:
            metadata["tender_id"] = payload.tender_id
        if payload.pack_code:
            metadata["pack_code"] = payload.pack_code
        if payload.delivery_address_code:
            metadata["delivery_address_code"] = payload.delivery_address_code

        self._activity_log_service.record_action(
            ActivityLogWrite(
                tenant_id=payload.tenant_id,
                workflow_lifecycle_id=payload.workflow_lifecycle_id,
                workflow_run_id=payload.workflow_run_id,
                description=format_workflow_error_alert_sent_action(
                    error_code=error_code,
                    message=str(payload.error.get("message") or "").strip() or None,
                ),
                metadata=metadata,
                communication_id=communication_id,
            )
        )
