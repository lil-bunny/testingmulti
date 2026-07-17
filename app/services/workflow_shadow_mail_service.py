"""Redirect workflow shadow-mode outbound mail to tenant-configured test inboxes."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.tools.email import send_email as send_email_tool

if TYPE_CHECKING:
    from app.domain.tenant_settings.email_recipients import EmailRecipients

logger = get_logger(__name__)

_SHADOW_SUBJECT_TAG = "[SHADOW]"


def _build_shadow_subject(subject: str, load_id: str | None = None) -> str:
    subject_clean = (subject or "").strip() or "Notification"
    if subject_clean.upper().startswith(_SHADOW_SUBJECT_TAG):
        subject_clean = subject_clean[len(_SHADOW_SUBJECT_TAG) :].strip()

    load_clean = (load_id or "").strip()
    if load_clean:
        return f"{_SHADOW_SUBJECT_TAG} {load_clean} {subject_clean}"
    return f"{_SHADOW_SUBJECT_TAG} {subject_clean}"


class WorkflowShadowMailService:
    def send_redirect_email(
        self,
        *,
        tenant_id: str,
        recipients: EmailRecipients,
        subject: str,
        body: str,
        account_id: str,
        from_email: str | None = None,
        workflow_run_id: str | None = None,
        load_id: str | None = None,
        communication_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Send a new outbound message (no thread reply) to shadow redirect recipients."""
        meta = dict(communication_metadata or {})
        effective_load_id = (load_id or meta.get("load_id") or "").strip() or None
        subject_clean = _build_shadow_subject(subject, effective_load_id)
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
            from_email=from_email,
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            communication_metadata=meta,
            cc=recipients.cc or None,
            bcc=recipients.bcc or None,
        )
