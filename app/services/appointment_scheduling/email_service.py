"""Outbound appointment scheduling draft email (Unipile + communications)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle.settings import mikey_unipile_from, resolve_mikey_mailbox
from app.domain.tenant_settings.email_recipients import (
    coerce_email_list,
    unipile_recipients_from_addresses,
)
from app.services.communications.service import CommunicationsService
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)


@dataclass(frozen=True)
class AppointmentSchedulingSendResult:
    sent: bool
    error: str | None = None
    communication_id: str | None = None
    send_result: dict[str, Any] | None = None


class AppointmentSchedulingEmailService:
    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
    ) -> None:
        self._communications = communications_service or CommunicationsService()

    @staticmethod
    def _draft_from_state(state) -> dict[str, Any]:
        meta = state.data.get("workflow_lifecycle_metadata") or {}
        if not isinstance(meta, dict):
            row = state.data.get("workflow_lifecycle_row") or {}
            meta = row.get("metadata") if isinstance(row, dict) else {}
        if not isinstance(meta, dict):
            return {}
        draft = meta.get("email_draft")
        return draft if isinstance(draft, dict) else {}

    @staticmethod
    def _validate_draft(draft: dict[str, Any]) -> tuple[str, str, str, list[str]] | None:
        to = str(draft.get("to") or "").strip()
        subject = str(draft.get("subject") or "").strip()
        body = str(draft.get("full_html") or "").strip()
        if not to or not subject or not body:
            return None
        cc_raw = draft.get("cc")
        cc = coerce_email_list(cc_raw, required=False) if cc_raw is not None else []
        return to, subject, body, cc

    def send_from_state(self, state) -> AppointmentSchedulingSendResult:
        data = state.data or {}
        draft = self._draft_from_state(state)
        validated = self._validate_draft(draft)
        if validated is None:
            logger.error(
                "appointment_draft_send missing draft fields lifecycle_id=%s",
                data.get("workflow_lifecycle_id"),
            )
            return AppointmentSchedulingSendResult(sent=False, error="missing_email_draft")

        to, subject, body, cc = validated
        tenant_raw = getattr(state, "tenant_id", None) or data.get("tenant_id")
        run_id = str(state.execution_id or "").strip() or None

        mailbox = resolve_mikey_mailbox(state)
        if not mailbox:
            logger.error(
                "appointment_draft_send mikey_account_id missing lifecycle_id=%s shipment_id=%s",
                data.get("workflow_lifecycle_id"),
                data.get("shipment_id"),
            )
            return AppointmentSchedulingSendResult(sent=False, error="missing_mikey_account_id")

        to_list = unipile_recipients_from_addresses([to])
        cc_list = unipile_recipients_from_addresses(cc) if cc else None
        from_recipient = mikey_unipile_from(mailbox)

        try:
            send_result = Unipile().send_email(
                to=to_list,
                subject=subject,
                body=body,
                account_id=mailbox.account_id,
                cc=cc_list,
                from_recipient=from_recipient,
            )
        except UnipileException as exc:
            logger.warning(
                "appointment_draft_send Unipile error lifecycle_id=%s: %s",
                data.get("workflow_lifecycle_id"),
                exc,
            )
            return AppointmentSchedulingSendResult(sent=False, error=str(exc))
        except Exception:
            logger.exception(
                "appointment_draft_send unexpected error lifecycle_id=%s",
                data.get("workflow_lifecycle_id"),
            )
            return AppointmentSchedulingSendResult(sent=False, error="unexpected_error")

        if not isinstance(send_result, dict) or not send_result.get("success", True):
            err = (
                (send_result or {}).get("error")
                if isinstance(send_result, dict)
                else None
            ) or "unipile_send_failed"
            return AppointmentSchedulingSendResult(
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

        return AppointmentSchedulingSendResult(
            sent=True,
            communication_id=comm_id,
            send_result=send_result,
        )


__all__ = ("AppointmentSchedulingEmailService", "AppointmentSchedulingSendResult")
