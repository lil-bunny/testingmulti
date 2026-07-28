"""Outbound appointment scheduling emails (draft send + confirmation thread reply)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.confirmation_reply import resolve_confirmation_reply_body
from app.domain.error_catalog import BusinessError
from app.domain.pod_lifecycle.settings import mikey_unipile_from, resolve_mikey_mailbox
from app.domain.tenant_settings.email_recipients import (
    coerce_email_list,
    unipile_recipients_from_addresses,
)
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)
from app.services.communications.service import CommunicationsService
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)


@dataclass(frozen=True)
class SendResult:
    sent: bool
    error: str | None = None
    communication_id: str | None = None
    send_result: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConfirmationEmailResult:
    sent: bool
    error: str | None = None
    communication_id: str | None = None


class EmailService:
    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
        activity_service: ActivityService | None = None,
    ) -> None:
        self._communications = communications_service or CommunicationsService()
        self._activity = activity_service or ActivityService()

    @staticmethod
    def _draft_from_state(state) -> dict[str, Any]:
        draft = state.data.get("email_draft")
        return draft if isinstance(draft, dict) else {}

    @staticmethod
    def _validate_draft(
        draft: dict[str, Any],
    ) -> tuple[list[str], str, str, list[str], list[str]] | None:
        to = coerce_email_list(draft.get("to"), required=False)
        subject = str(draft.get("subject") or "").strip()
        body = str(draft.get("full_html") or "").strip()
        if not to or not subject or not body:
            return None
        cc = coerce_email_list(draft.get("cc"), required=False)
        bcc = coerce_email_list(draft.get("bcc"), required=False)
        return to, subject, body, cc, bcc

    def send_draft_from_state(self, state) -> SendResult:
        data = state.data or {}
        draft = self._draft_from_state(state)
        validated = self._validate_draft(draft)
        if validated is None:
            logger.error(
                "appointment_draft_send missing draft fields lifecycle_id=%s",
                data.get("workflow_lifecycle_id"),
            )
            return SendResult(sent=False, error=BusinessError.SCHEDULING_DRAFT_NOT_READY.value)

        to_addrs, subject, body, cc, bcc = validated
        tenant_raw = getattr(state, "tenant_id", None) or data.get("tenant_id")
        run_id = str(state.execution_id or "").strip() or None

        mailbox = resolve_mikey_mailbox(state)
        if not mailbox:
            logger.error(
                "appointment_draft_send mikey_account_id missing lifecycle_id=%s shipment_id=%s",
                data.get("workflow_lifecycle_id"),
                data.get("shipment_id"),
            )
            return SendResult(sent=False, error=BusinessError.MISSING_MIKEY_ACCOUNT_ID.value)

        tenant_id = str(tenant_raw or "").strip()
        lifecycle_id = str(data.get("workflow_lifecycle_id") or "").strip()
        if tenant_id and lifecycle_id:
            existing = self._communications.find_outbound_draft_communication_id(
                tenant_id=tenant_id,
                workflow_lifecycle_id=lifecycle_id,
            )
            if existing:
                state.data["communication_id"] = existing
                return SendResult(sent=True, communication_id=existing)

        to_list = unipile_recipients_from_addresses(to_addrs)
        cc_list = unipile_recipients_from_addresses(cc) if cc else None
        bcc_list = unipile_recipients_from_addresses(bcc) if bcc else None
        from_recipient = mikey_unipile_from(mailbox)

        try:
            send_result = Unipile().send_email(
                to=to_list,
                subject=subject,
                body=body,
                account_id=mailbox.account_id,
                cc=cc_list,
                bcc=bcc_list,
                from_recipient=from_recipient,
            )
        except UnipileException as exc:
            logger.warning(
                "appointment_draft_send Unipile error lifecycle_id=%s: %s",
                data.get("workflow_lifecycle_id"),
                exc,
            )
            return SendResult(sent=False, error=str(exc))
        except Exception:
            logger.exception(
                "appointment_draft_send unexpected error lifecycle_id=%s",
                data.get("workflow_lifecycle_id"),
            )
            return SendResult(sent=False, error="unexpected_error")

        if not isinstance(send_result, dict) or not send_result.get("success", True):
            err = (
                (send_result or {}).get("error")
                if isinstance(send_result, dict)
                else None
            ) or "unipile_send_failed"
            return SendResult(
                sent=False,
                error=str(err),
                send_result=send_result if isinstance(send_result, dict) else None,
            )

        comm_id = self._communications.record_outbound_from_send(
            str(tenant_raw or "").strip(),
            send_result=send_result,
            body=body,
            subject=subject,
            to=to_list,
            cc=cc_list,
            account_id=mailbox.account_id,
            from_email=mailbox.email_alias,
            extra_metadata={
                "source": "appointment_draft_send",
                "workflow_lifecycle_id": data.get("workflow_lifecycle_id"),
                "shipment_id": data.get("shipment_id"),
            },
            workflow_run_id=run_id,
        )
        if comm_id:
            send_result["communication_id"] = comm_id
            state.data["communication_id"] = comm_id

        return SendResult(
            sent=True,
            communication_id=comm_id,
            send_result=send_result,
        )

    def send_confirmation_reply_from_state(self, state) -> ConfirmationEmailResult:
        data = state.data or {}
        tenant_id = (getattr(state, "tenant_id", None) or data.get("tenant_id") or "").strip()
        thread_id = str(data.get("thread_id") or "").strip()
        run_id = str(getattr(state, "execution_id", None) or data.get("execution_id") or "").strip()
        if not tenant_id or not thread_id:
            return ConfirmationEmailResult(sent=False, error=BusinessError.SCHEDULING_DRAFT_NOT_READY.value)

        mailbox = resolve_mikey_mailbox(state)
        if not mailbox:
            return ConfirmationEmailResult(sent=False, error=BusinessError.MISSING_MIKEY_ACCOUNT_ID.value)

        tenant_settings = data.get("tenant_settings")
        if not isinstance(tenant_settings, dict):
            tenant_settings = {}
        body = resolve_confirmation_reply_body(tenant_settings, data)

        try:
            result = self._communications.send_thread_reply(
                tenant_id=tenant_id,
                thread_id=thread_id,
                body=body,
                account_id=mailbox.account_id,
                from_email=mailbox.email_alias,
                workflow_run_id=run_id or None,
                communication_metadata={
                    "source": "appointment_confirmation_reply",
                    "workflow_lifecycle_id": data.get("workflow_lifecycle_id"),
                    "shipment_id": data.get("shipment_id"),
                    "reference_number": data.get("reference_number"),
                },
            )
        except UnipileException as exc:
            logger.warning(
                "appointment confirmation reply failed lifecycle_id=%s: %s",
                data.get("workflow_lifecycle_id"),
                exc,
            )
            return ConfirmationEmailResult(sent=False, error=str(exc))
        except Exception:
            logger.exception(
                "appointment confirmation reply unexpected error lifecycle_id=%s",
                data.get("workflow_lifecycle_id"),
            )
            return ConfirmationEmailResult(sent=False, error="unexpected_error")

        comm_id = str(result.get("communication_id") or "").strip() or None
        if comm_id:
            state.data["confirmation_communication_id"] = comm_id
            self._activity.record_confirmation_sent(state)
        return ConfirmationEmailResult(sent=True, communication_id=comm_id)


__all__ = (
    "EmailService",
    "SendResult",
    "ConfirmationEmailResult",
)
