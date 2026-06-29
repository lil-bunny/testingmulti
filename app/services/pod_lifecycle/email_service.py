"""POD lifecycle outbound email (Unipile)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle_settings import resolve_pod_sender_account_id
from app.domain.tenant_settings.workflow_shadow_mode import (
    parse_shadow_mail_recipients,
    workflow_shadow_active,
)
from app.services.unipile_service import UnipileException
from app.services.workflow_shadow_mail_service import WorkflowShadowMailService
from app.tools.email import send_email as send_email_tool

logger = get_logger(__name__)


@dataclass(frozen=True)
class PodReminderSendResult:
    sent: bool
    error: str | None = None
    send_result: dict[str, Any] | None = None
    communication_id: str | None = None
    shadow_skipped: bool = False

    def to_state_patch(self) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "pod_reminder_sent": self.sent,
            "pod_reminder_result": self.send_result,
        }
        if self.error:
            patch["pod_reminder_error"] = self.error
        if self.shadow_skipped:
            patch["pod_reminder_shadow_skipped"] = True
        if self.communication_id:
            patch["communication_id"] = self.communication_id
        return patch


class PodLifecycleEmailService:
    @staticmethod
    def _result_from_send(send_result: dict[str, Any] | None) -> PodReminderSendResult:
        if send_result is None:
            return PodReminderSendResult(sent=False, error="send_skipped_or_no_result")
        success = True
        if isinstance(send_result, dict):
            success = bool(send_result.get("success", True))
        if not success:
            err = (
                (send_result or {}).get("error")
                if isinstance(send_result, dict)
                else None
            ) or "unipile_send_failed"
            return PodReminderSendResult(
                sent=False,
                error=str(err),
                send_result=send_result if isinstance(send_result, dict) else None,
            )
        comm_id = None
        if isinstance(send_result, dict):
            raw = send_result.get("communication_id")
            if raw is not None and str(raw).strip():
                comm_id = str(raw).strip()
        return PodReminderSendResult(
            sent=True,
            send_result=send_result if isinstance(send_result, dict) else None,
            communication_id=comm_id,
        )

    def send_pod_reminder_from_state(self, state) -> PodReminderSendResult:
        data = state.data or {}
        tenant_raw = getattr(state, "tenant_id", None) or data.get("tenant_id")
        run_id = str(state.execution_id or "").strip() or None
        tenant_settings = data.get("tenant_settings") if isinstance(data.get("tenant_settings"), dict) else None

        sender_account_id = resolve_pod_sender_account_id(state)
        if not sender_account_id:
            logger.error(
                "send_pod_reminder mikey_account_id missing lifecycle_id=%s shipment_id=%s",
                data.get("workflow_lifecycle_id"),
                data.get("shipment_id"),
            )
            return PodReminderSendResult(sent=False, error="missing_mikey_account_id")

        subject = str(data.get("subject") or "POD Request").strip() or "POD Request"
        body = str(data.get("body") or "")

        if workflow_shadow_active(
            tenant_settings,
            data,
            workflow_name="pod_lifecycle",
        ):
            redirect = parse_shadow_mail_recipients(
                tenant_settings,
                workflow_name="pod_lifecycle",
            )
            if redirect is None:
                logger.info(
                    "send_pod_reminder shadow_mode skipped outbound email lifecycle_id=%s shipment_id=%s",
                    data.get("workflow_lifecycle_id"),
                    data.get("shipment_id"),
                )
                return PodReminderSendResult(sent=True, shadow_skipped=True)
            try:
                send_result = WorkflowShadowMailService().send_redirect_email(
                    tenant_id=str(tenant_raw or "").strip(),
                    recipients=redirect,
                    subject=subject,
                    body=body,
                    account_id=sender_account_id,
                    workflow_run_id=run_id,
                    communication_metadata={
                        "source": "pod_send_email",
                        "workflow_lifecycle_id": data.get("workflow_lifecycle_id"),
                        "shipment_id": data.get("shipment_id"),
                        "load_id": data.get("load_id"),
                        "email_id": data.get("email_id"),
                        "original_thread_id": data.get("thread_id"),
                    },
                )
            except UnipileException as exc:
                logger.warning(
                    "send_pod_reminder shadow redirect Unipile error lifecycle_id=%s shipment_id=%s: %s",
                    data.get("workflow_lifecycle_id"),
                    data.get("shipment_id"),
                    exc,
                )
                return PodReminderSendResult(sent=False, error=str(exc))
            except Exception:
                logger.exception(
                    "send_pod_reminder shadow redirect unexpected error lifecycle_id=%s shipment_id=%s",
                    data.get("workflow_lifecycle_id"),
                    data.get("shipment_id"),
                )
                return PodReminderSendResult(sent=False, error="unexpected_error")
            return self._result_from_send(send_result)

        send_result = None
        try:
            send_result = send_email_tool(
                data.get("to"),
                subject,
                body,
                thread_id=data.get("thread_id"),
                account_id=sender_account_id,
                tenant_id=tenant_raw,
                workflow_run_id=run_id,
                communication_metadata={
                    "source": "pod_send_email",
                    "thread_id": data.get("thread_id"),
                    "email_id": data.get("email_id"),
                    "workflow_lifecycle_id": data.get("workflow_lifecycle_id"),
                    "shipment_id": data.get("shipment_id"),
                },
            )
        except UnipileException as exc:
            logger.warning(
                "send_pod_reminder Unipile error lifecycle_id=%s shipment_id=%s: %s",
                data.get("workflow_lifecycle_id"),
                data.get("shipment_id"),
                exc,
            )
            return PodReminderSendResult(sent=False, error=str(exc), send_result=send_result)
        except Exception:
            logger.exception(
                "send_pod_reminder unexpected error lifecycle_id=%s shipment_id=%s",
                data.get("workflow_lifecycle_id"),
                data.get("shipment_id"),
            )
            return PodReminderSendResult(sent=False, error="unexpected_error", send_result=send_result)

        return self._result_from_send(send_result)
