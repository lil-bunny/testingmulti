"""Redirect workflow shadow-mode outbound mail to tenant-configured test inboxes."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.tenant_settings.email_recipients import EmailRecipients
from app.tools.email import send_email as send_email_tool

logger = get_logger(__name__)

_SHADOW_SUBJECT_PREFIX = "[SHADOW] "


class WorkflowShadowMailService:
    def send_redirect_email(
        self,
        *,
        tenant_id: str,
        recipients: EmailRecipients,
        subject: str,
        body: str,
        account_id: str,
        workflow_run_id: str | None = None,
        communication_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Send a new outbound message (no thread reply) to shadow redirect recipients."""
        subject_clean = (subject or "").strip() or "Notification"
        if not subject_clean.startswith(_SHADOW_SUBJECT_PREFIX.strip()):
            subject_clean = f"{_SHADOW_SUBJECT_PREFIX}{subject_clean}"

        meta = dict(communication_metadata or {})
        meta.setdefault("shadow_mail_redirect", True)
        meta.setdefault("shadow_mail_to", list(recipients.to))

        logger.info(
            "shadow_mail redirect send tenant_id=%s to=%s subject=%r",
            tenant_id,
            recipients.to,
            subject_clean[:120],
        )

        return send_email_tool(
            recipients.to,
            subject=subject_clean,
            body=body,
            thread_id=None,
            account_id=account_id,
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            communication_metadata=meta,
            cc=recipients.cc or None,
            bcc=recipients.bcc or None,
        )
