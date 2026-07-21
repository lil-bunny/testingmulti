"""Thank-you thread reply after appointment confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.confirmation_reply import resolve_confirmation_reply_body
from app.domain.pod_lifecycle.settings import resolve_mikey_mailbox
from app.services.communications.service import CommunicationsService
from app.services.unipile_service import UnipileException

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConfirmationEmailResult:
    sent: bool
    error: str | None = None
    communication_id: str | None = None


class AppointmentSchedulingConfirmationEmailService:
    def __init__(
        self,
        *,
        communications_service: CommunicationsService | None = None,
    ) -> None:
        self._communications = communications_service or CommunicationsService()

    def send_from_state(self, state) -> ConfirmationEmailResult:
        data = state.data or {}
        tenant_id = (getattr(state, "tenant_id", None) or data.get("tenant_id") or "").strip()
        thread_id = str(data.get("thread_id") or "").strip()
        run_id = str(getattr(state, "execution_id", None) or data.get("execution_id") or "").strip()
        if not tenant_id or not thread_id:
            return ConfirmationEmailResult(sent=False, error="missing_thread_or_tenant")

        mailbox = resolve_mikey_mailbox(state)
        if not mailbox:
            return ConfirmationEmailResult(sent=False, error="missing_mikey_account_id")

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
        return ConfirmationEmailResult(sent=True, communication_id=comm_id)


__all__ = (
    "AppointmentSchedulingConfirmationEmailService",
    "ConfirmationEmailResult",
)
