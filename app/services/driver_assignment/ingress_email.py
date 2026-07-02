"""Driver assignment reminder and confirmation emails."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.driver_assignment.confirmation_email import parse_driver_assignment_confirmation_email
from app.domain.driver_assignment.partial_follow_up_email import (
    resolve_partial_follow_up_email,
)
from app.domain.tenant_settings.workflow_shadow_mode import (
    parse_shadow_mail_recipients,
    workflow_shadow_active,
)
from app.domain.pod_lifecycle_settings import resolve_mikey_mailbox
from app.tools.driver_details import render_driver_confirmation_html
from app.services.driver_assignment.ingress_types import SendReminderResult
from app.services.unipile_service import UnipileException
from app.services.workflow_shadow_mail_service import WorkflowShadowMailService

logger = get_logger(__name__)

class IngressEmailMixin:
    def send_reminder_email(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        workflow_run_id: str | None = None,

        ) -> SendReminderResult:

        thread_id = self._clean(payload.get("thread_id"))

        ratecon_lifecycle_id = self._clean(payload.get("ratecon_workflow_lifecycle_id"))

        if not thread_id and ratecon_lifecycle_id:

            thread_id = self._communications.resolve_thread_for_lifecycle(

                tenant_id=tenant_id,

                workflow_lifecycle_id=ratecon_lifecycle_id,

            )

        settings = tenant_settings or {}

        mailbox = resolve_mikey_mailbox({"tenant_settings": settings})
        if not mailbox:
            return SendReminderResult(sent=False, error="missing_mikey_account_id")

        account_id = mailbox.account_id
        from_email = mailbox.email_alias

        if not thread_id:

            if not workflow_shadow_active(
                settings,
                payload,
                workflow_name="driver_assignment",
            ) or parse_shadow_mail_recipients(
                settings,
                workflow_name="driver_assignment",
            ) is None:
                return SendReminderResult(sent=False, error="missing_thread_id")

        reminder_step = payload.get("reminder_step")

        subject = self._clean(payload.get("subject"))

        if not subject:

            step_label = int(reminder_step) if reminder_step is not None else 0

            subject = f"Driver assignment reminder (step {step_label})"

        body = (str(payload.get("body") or "").strip()) or (

            "Please provide driver name and contact information for this load."

        )

        email_source = (
            self._clean(payload.get("reminder_email_source"))
            or "driver_assignment_reminder"
        )

        if workflow_shadow_active(
            settings,
            payload,
            workflow_name="driver_assignment",
        ):
            redirect = parse_shadow_mail_recipients(
                settings,
                workflow_name="driver_assignment",
            )
            if redirect is None:
                logger.info(
                    "send_reminder_email shadow_mode skipped outbound email lifecycle_id=%s shipment_id=%s",
                    payload.get("workflow_lifecycle_id"),
                    payload.get("shipment_id"),
                )
                return SendReminderResult(sent=True)
            try:
                result = WorkflowShadowMailService().send_redirect_email(
                    tenant_id=tenant_id,
                    recipients=redirect,
                    subject=subject,
                    body=body,
                    account_id=account_id,
                    from_email=from_email,
                    workflow_run_id=workflow_run_id,
                    communication_metadata={
                        "source": email_source,
                        "workflow_lifecycle_id": payload.get("workflow_lifecycle_id"),
                        "shipment_id": payload.get("shipment_id"),
                        "load_id": payload.get("load_id"),
                        "reminder_step": reminder_step,
                        "original_thread_id": thread_id,
                    },
                )
            except UnipileException as exc:
                logger.warning(
                    "send_reminder_email shadow redirect Unipile error lifecycle_id=%s shipment_id=%s: %s",
                    payload.get("workflow_lifecycle_id"),
                    payload.get("shipment_id"),
                    exc,
                )
                return SendReminderResult(sent=False, error=str(exc))
            except Exception:
                logger.exception(
                    "send_reminder_email shadow redirect unexpected error lifecycle_id=%s shipment_id=%s",
                    payload.get("workflow_lifecycle_id"),
                    payload.get("shipment_id"),
                )
                return SendReminderResult(sent=False, error="unexpected_error")
            return self._reminder_result_from_send(result)

        try:

            result = self._communications.send_thread_reply(

                tenant_id=tenant_id,

                thread_id=thread_id,

                body=body,

                account_id=account_id,

                from_email=from_email,

                subject=subject,

                workflow_run_id=workflow_run_id,

                communication_metadata={

                    "source": email_source,

                    "thread_id": thread_id,

                    "workflow_lifecycle_id": payload.get("workflow_lifecycle_id"),

                    "shipment_id": payload.get("shipment_id"),

                    "reminder_step": reminder_step,

                },

            )

        except UnipileException as exc:

            logger.warning(

                "send_reminder_email Unipile error lifecycle_id=%s shipment_id=%s: %s",

                payload.get("workflow_lifecycle_id"),

                payload.get("shipment_id"),

                exc,

            )

            return SendReminderResult(sent=False, error=str(exc))

        except Exception:

            logger.exception(

                "send_reminder_email unexpected error lifecycle_id=%s shipment_id=%s",

                payload.get("workflow_lifecycle_id"),

                payload.get("shipment_id"),

            )

            return SendReminderResult(sent=False, error="unexpected_error")

        return self._reminder_result_from_send(result)

    @staticmethod
    def _reminder_result_from_send(result: Any) -> SendReminderResult:
        if result is None:
            return SendReminderResult(sent=False, error="send_skipped_or_no_result")
        success = True
        if isinstance(result, dict):
            success = bool(result.get("success", True))
        elif result is False:
            success = False
        if not success:
            err = (result or {}).get("error") if isinstance(result, dict) else None
            return SendReminderResult(sent=False, error=str(err or "send_failed"))
        comm_id = None
        if isinstance(result, dict):
            raw = result.get("communication_id")
            if raw is not None and str(raw).strip():
                comm_id = str(raw).strip()
        return SendReminderResult(sent=True, error=None, communication_id=comm_id)

    def send_partial_details_follow_up_email(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        workflow_run_id: str | None = None,

        ) -> SendReminderResult:

        wl_id = self._clean(payload.get("workflow_lifecycle_id"))

        if not wl_id:

            return SendReminderResult(sent=False, error="missing_workflow_lifecycle_id")

        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

        current_step = self._reminder_step_from_lifecycle_row(row)

        at_cap = current_step >= 4

        # ponytail: at ladder max still send chase mail; sub-status bump handled in activity
        log_step = 4 if at_cap else current_step + 1

        send_payload = dict(payload)

        send_payload["reminder_step"] = log_step

        send_payload["body"] = resolve_partial_follow_up_email(tenant_settings)
        send_payload.pop("subject", None)

        send_payload["reminder_email_source"] = "driver_details_partial_follow_up"

        result = self.send_reminder_email(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=send_payload,

            workflow_run_id=workflow_run_id,

        )

        return SendReminderResult(

            sent=result.sent,

            error=result.error,

            communication_id=result.communication_id,

            reminder_step=log_step if result.sent else None,

            skip_sub_status_bump=at_cap and result.sent,

        )

    def send_driver_details_confirmation_email(
        self,
        *,
        tenant_id: str,
        tenant_settings: dict[str, Any] | None,
        payload: dict[str, Any],
        workflow_run_id: str | None = None,
        ) -> SendReminderResult:
        resolution = str(payload.get("tms_resolution") or "").strip()
        if resolution == "skipped_already_assigned":
            return SendReminderResult(sent=False, error="skipped_already_assigned")
        if str(payload.get("tms_driver_outcome") or "").strip() != "assigned":
            return SendReminderResult(sent=False, error="not_assigned")
        if resolution not in ("found", "created", "assigned"):
            return SendReminderResult(sent=False, error="not_assigned")

        conf = parse_driver_assignment_confirmation_email(tenant_settings)
        if conf is None:
            return SendReminderResult(sent=False, error="missing_confirmation_email_config")

        is_tracking = bool(payload.get("tms_is_tracking_customer"))
        template = conf.template_html_for(is_tracking_customer=is_tracking)
        if not template:
            variant = conf.variant_key_for(is_tracking_customer=is_tracking)
            return SendReminderResult(sent=False, error=f"missing_{variant}_template_html")

        extraction = payload.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        if not isinstance(driver, dict):
            driver = {}

        body = render_driver_confirmation_html(
            template,
            driver_name=payload.get("tms_matched_driver_name") or driver.get("name"),
            driver_phone=payload.get("tms_matched_driver_phone") or driver.get("phone"),
        )
        send_payload = dict(payload)
        send_payload["body"] = body
        send_payload.pop("subject", None)
        send_payload["reminder_email_source"] = "driver_details_confirmation"
        send_payload["driver_confirmation_variant"] = conf.variant_key_for(
            is_tracking_customer=is_tracking
        )

        return self.send_reminder_email(
            tenant_id=tenant_id,
            tenant_settings=tenant_settings,
            payload=send_payload,
            workflow_run_id=workflow_run_id,
        )
