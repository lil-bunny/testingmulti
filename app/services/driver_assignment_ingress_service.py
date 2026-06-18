"""Pre-enqueue and pre-graph ingress for ``driver_assignment`` (ratecon_completed)."""



from __future__ import annotations



import uuid

from dataclasses import dataclass

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger

from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db

from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings

from app.integrations.turvo.shipments import (

    driver_assigned_from_payload,

    driver_request_eligible_from_payload,

    pickup_appointment_from_payload,

)

from app.models.status import StatusSubType, StatusType

from app.models.tenants import TenantSlug

from app.models.workflow_run_event_type import WorkflowRunEventType

from app.services.communications.service import CommunicationsService

from app.services.driver_assignment_activity_service import DriverAssignmentActivityService

from app.services.shipments_service import ShipmentsService

from app.services.tenants_service import TenantsService

from app.services.unipile_service import UnipileException

from app.services.workflow_lifecycle_service import WorkflowLifecycleService

from app.services.workflow_runs_service import WorkflowRunsService

from app.services.unipile_tenant_resolution import UnipileTenantContext



logger = get_logger(__name__)



DRIVER_ASSIGNMENT_WORKFLOW = "driver_assignment"

RATECON_WORKFLOW = "ratecon"

_DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML = (
    "<html><body>"
    "<p>Thanks for your reply.</p>"
    "<p>We still need <strong>complete driver details</strong> for this load.</p>"
    "<p>Please reply with the driver&apos;s <strong>full name</strong> and "
    "<strong>mobile number</strong> (or email address).</p>"
    "<p>If you already sent this, please reply again with both in one message.</p>"
    "</body></html>"
)



_PREPARE_REQUIRED_KEYS = (

    "load_id",

    "shipments_row_id",

    "shipment_id",

    "ratecon_workflow_lifecycle_id",

)



_LAYER1_ACTIVITY_SKIP_REASONS = frozenset(

    {

        "pickup_appointment_not_found",

        "driver_already_assigned",

        "shipment_not_in_state",

        "transportation_mode_not_tl",

        "shipment_not_covered",

        "excluded_carrier",

    }

)





@dataclass(frozen=True)

class EnqueueResult:

    enqueued: bool

    skip_reason: str | None = None

    execution_id: str | None = None

    celery_task_id: str | None = None





@dataclass(frozen=True)

class PrepareResult:

    skipped: bool

    skip_reason: str | None = None

    payload: dict[str, Any] | None = None





@dataclass(frozen=True)

class EligibilityResult:

    skip_reason: str | None = None



    @property

    def eligible(self) -> bool:

        return self.skip_reason is None





@dataclass(frozen=True)

class SendReminderResult:

    sent: bool

    error: str | None = None

    communication_id: str | None = None

    reminder_step: int | None = None

    skip_sub_status_bump: bool = False





class DriverAssignmentIngressService:

    """Layers 1–2 ingress and shared layer-3 eligibility for driver assignment."""



    def __init__(

        self,

        *,

        lifecycle_service: WorkflowLifecycleService | None = None,

        runs_service: WorkflowRunsService | None = None,

        shipments_service: ShipmentsService | None = None,

        communications_service: CommunicationsService | None = None,

        activity_service: DriverAssignmentActivityService | None = None,

    ) -> None:

        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()

        self._runs_service = runs_service or WorkflowRunsService()

        self._shipments = shipments_service or ShipmentsService()

        self._communications = communications_service or CommunicationsService()

        self._activity = activity_service or DriverAssignmentActivityService()



    @staticmethod

    def _clean(value: Any) -> str | None:

        if value is None:

            return None

        s = str(value).strip()

        return s if s else None



    @staticmethod

    def _ratecon_upload_success(data: dict[str, Any]) -> bool:

        upload_result = data.get("ratecon_s3_upload")

        if not isinstance(upload_result, dict):

            return False

        if upload_result.get("skipped"):

            return False

        if not upload_result.get("all_succeeded"):

            return False

        for item in upload_result.get("results") or []:

            if not isinstance(item, dict):

                continue

            persist = item.get("document_persist") or {}

            if persist.get("stored"):

                return True

        return False



    @staticmethod

    def _ratecon_analysis_success(data: dict[str, Any]) -> bool:

        persist = data.get("document_analysis_ratecon")

        return isinstance(persist, dict) and persist.get("stored") is True



    @staticmethod

    def _is_process_enabled(tenant_settings: dict[str, Any] | None) -> bool:

        return DRIVER_ASSIGNMENT_WORKFLOW in enabled_processes_from_settings(

            tenant_settings

        )



    @staticmethod

    def _driver_request_skip_reason(turvo_payload: Any) -> str | None:

        if not isinstance(turvo_payload, dict):

            return "shipment_not_in_state"

        return driver_request_eligible_from_payload(turvo_payload)



    @staticmethod

    def _enrich_pickup_from_turvo_payload(

        turvo_payload: Any,

    ) -> tuple[str | None, dict[str, Any]]:

        if not isinstance(turvo_payload, dict):

            return "shipment_not_in_state", {}



        if driver_assigned_from_payload(turvo_payload):

            return "driver_already_assigned", {}



        pickup = pickup_appointment_from_payload(turvo_payload)

        if pickup is None:

            return "pickup_appointment_not_found", {}



        return None, {

            "pickup_appointment_at": pickup.at_utc.isoformat(),

            "pickup_appointment_timezone": pickup.timezone,

            "pickup_appointment_source": pickup.source,

            "shipment": turvo_payload,

        }



    @staticmethod

    def _ensure_pickup_on_payload(payload: dict[str, Any]) -> None:

        if DriverAssignmentIngressService._clean(payload.get("pickup_appointment_at")):

            return



        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            pickup = pickup_appointment_from_payload(shipment)

            if pickup is not None:

                payload["pickup_appointment_at"] = pickup.at_utc.isoformat()

                payload["pickup_appointment_timezone"] = pickup.timezone

                payload["pickup_appointment_source"] = pickup.source

                return



        raise Exception("Missing pickup_appointment_at for 'driver_assignment'")



    def _driver_lifecycle_terminal(

        self,

        *,

        tenant_id: str,

        shipments_row_id: str,

    ) -> bool:

        lifecycle = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_id,

            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,

            shipment_id=shipments_row_id,

        )

        if not lifecycle.get("exists"):

            return False

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id"))

        if not lifecycle_id:

            return False

        row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id)

        if not row:

            return False

        sub = sub_status_type_from_db(row.get("sub_status"))

        return sub in (
            StatusSubType.UPLOADED_TO_TMS,
            StatusSubType.DETAILS_RECEIVED,
        )



    def _ratecon_lifecycle_complete(self, ratecon_lifecycle_id: str) -> bool:

        row = self._lifecycle_service.read_lifecycle_row_by_id(ratecon_lifecycle_id)

        if not row:

            return False

        status = status_type_from_db(row.get("status"))

        sub = sub_status_type_from_db(row.get("sub_status"))

        return (

            status == StatusType.COMPLETED

            and sub == StatusSubType.DOCUMENT_PROCESSED

        )



    def _is_duplicate_ratecon_completed(

        self,

        *,

        tenant_id: str,

        shipments_row_id: str,

        exclude_run_id: str | None = None,

    ) -> bool:

        lifecycle = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_id,

            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,

            shipment_id=shipments_row_id,

        )

        if not lifecycle.get("exists"):

            return False

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id"))

        if not lifecycle_id:

            return False

        return self._runs_service.is_workflow_initial_path_blocked(

            tenant_id=tenant_id,

            event_type=WorkflowRunEventType.RATECON_COMPLETED.value,

            workflow_lifecycle_id=lifecycle_id,

            shipment_id=shipments_row_id,

            exclude_run_id=exclude_run_id,

        )



    def _resolve_thread_id(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

    ) -> str | None:

        thread_id = self._clean(payload.get("thread_id"))

        if thread_id:

            return thread_id

        ratecon_lifecycle_id = self._clean(payload.get("ratecon_workflow_lifecycle_id"))

        if not ratecon_lifecycle_id:

            return None

        return self._communications.resolve_thread_for_lifecycle(

            tenant_id=tenant_id,

            workflow_lifecycle_id=ratecon_lifecycle_id,

        )



    def _evaluate_start_gates(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        require_process_enabled: bool = True,

        exclude_run_id: str | None = None,

    ) -> str | None:

        if require_process_enabled and not self._is_process_enabled(tenant_settings):

            return "process_disabled"



        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        load_id = self._clean(payload.get("load_id"))

        shipment_id = self._clean(payload.get("shipment_id"))

        ratecon_lifecycle_id = self._clean(

            payload.get("ratecon_workflow_lifecycle_id")

        )

        if not all((shipments_row_id, load_id, shipment_id, ratecon_lifecycle_id)):

            return "missing_correlation_keys"



        thread_id = self._resolve_thread_id(tenant_id=tenant_id, payload=payload)

        if not thread_id:

            return "missing_thread_id"



        ratecon_row = self._lifecycle_service.read_lifecycle_row_by_id(

            ratecon_lifecycle_id

        )

        if not ratecon_row:

            return "ratecon_lifecycle_not_found"

        if not self._ratecon_lifecycle_complete(ratecon_lifecycle_id):

            return "ratecon_not_complete"



        shipment_row = self._shipments.get_by_id(

            tenant_id=tenant_id,

            shipment_id=shipments_row_id,

        )

        if not shipment_row:

            return "shipment_not_found"



        if self._driver_lifecycle_terminal(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

        ):

            return "already_completed"



        if self._is_duplicate_ratecon_completed(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

            exclude_run_id=exclude_run_id,

        ):

            return "duplicate_ratecon_completed"



        return None



    def _log_layer1_skip_on_ratecon(

        self,

        *,

        state,

        tenant_id: str,

        skip_reason: str,

        payload: dict[str, Any],

        pickup_fields: dict[str, Any] | None = None,

    ) -> None:

        if skip_reason not in _LAYER1_ACTIVITY_SKIP_REASONS:

            return



        ratecon_wl = self._clean(

            state.data.get("workflow_lifecycle_id") if hasattr(state, "data") else None

        )

        run_id = self._clean(getattr(state, "execution_id", None))

        if not ratecon_wl or not tenant_id or not run_id:

            return



        pf = pickup_fields or {}

        self._activity.record_not_started_on_ratecon(

            tenant_id=tenant_id,

            ratecon_workflow_lifecycle_id=ratecon_wl,

            workflow_run_id=run_id,

            skip_reason=skip_reason,

            shipment_id=self._clean(payload.get("shipment_id")),

            load_id=self._clean(payload.get("load_id")),

            shipments_row_id=self._clean(payload.get("shipments_row_id")),

            pickup_appointment_at=self._clean(pf.get("pickup_appointment_at")),

            pickup_appointment_timezone=self._clean(pf.get("pickup_appointment_timezone")),

        )



    def try_enqueue_from_ratecon_state(self, state) -> EnqueueResult:

        """Layer 1: silent skip or enqueue Celery from ratecon graph tail."""

        data = state.data if hasattr(state, "data") else {}

        tenant_id = self._clean(getattr(state, "tenant_id", None) or data.get("tenant_id"))

        tenant_slug = self._clean(data.get("tenant_slug")) or TenantSlug.T3RA.value

        tenant_settings = data.get("tenant_settings") or {}



        if data.get("error"):

            return EnqueueResult(enqueued=False, skip_reason="workflow_error")



        if not self._ratecon_upload_success(data):

            return EnqueueResult(

                enqueued=False,

                skip_reason="ratecon_upload_not_succeeded",

            )



        if not self._ratecon_analysis_success(data):

            return EnqueueResult(

                enqueued=False,

                skip_reason="ratecon_analysis_not_stored",

            )



        shipments_row_id = self._clean(data.get("shipments_row_id"))

        load_id = self._clean(data.get("load_id"))

        shipment_id = self._clean(data.get("shipment_id"))

        ratecon_workflow_lifecycle_id = self._clean(data.get("workflow_lifecycle_id"))

        if not tenant_id or not all(

            (shipments_row_id, load_id, shipment_id, ratecon_workflow_lifecycle_id)

        ):

            return EnqueueResult(

                enqueued=False,

                skip_reason="missing_correlation_keys",

            )



        thread_id = self._clean(data.get("thread_id"))

        if not thread_id and ratecon_workflow_lifecycle_id:

            thread_id = self._communications.resolve_thread_for_lifecycle(

                tenant_id=tenant_id,

                workflow_lifecycle_id=ratecon_workflow_lifecycle_id,

            )

        if not thread_id:

            return EnqueueResult(enqueued=False, skip_reason="missing_thread_id")



        payload = {

            "event_type": WorkflowRunEventType.RATECON_COMPLETED.value,

            "tenant_id": tenant_id,

            "tenant_slug": tenant_slug,

            "shipment_id": shipment_id,

            "shipments_row_id": shipments_row_id,

            "load_id": load_id,

            "thread_id": thread_id,

            "ratecon_workflow_lifecycle_id": ratecon_workflow_lifecycle_id,

            "communication_id": self._clean(data.get("communication_id")),

        }



        turvo_payload = data.get("shipment")

        eligibility_skip = self._driver_request_skip_reason(turvo_payload)

        if eligibility_skip:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                eligibility_skip,

                shipment_id,

                load_id,

            )

            self._log_layer1_skip_on_ratecon(

                state=state,

                tenant_id=tenant_id,

                skip_reason=eligibility_skip,

                payload=payload,

            )

            return EnqueueResult(enqueued=False, skip_reason=eligibility_skip)



        pickup_skip, pickup_fields = self._enrich_pickup_from_turvo_payload(

            turvo_payload

        )

        if pickup_skip:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                pickup_skip,

                shipment_id,

                load_id,

            )

            self._log_layer1_skip_on_ratecon(

                state=state,

                tenant_id=tenant_id,

                skip_reason=pickup_skip,

                payload=payload,

                pickup_fields=pickup_fields,

            )

            return EnqueueResult(enqueued=False, skip_reason=pickup_skip)



        payload.update(pickup_fields)



        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=payload,

        )

        if skip_reason:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                skip_reason,

                shipment_id,

                load_id,

            )

            return EnqueueResult(enqueued=False, skip_reason=skip_reason)



        execution_id = str(uuid.uuid4())

        payload["execution_id"] = execution_id



        from app.tasks.workflows import run_workflow_async



        task = run_workflow_async.apply_async(

            kwargs={

                "tenant_slug": tenant_slug,

                "workflow_name": DRIVER_ASSIGNMENT_WORKFLOW,

                "payload": payload,

            }

        )

        logger.info(

            "driver_assignment queued task_id=%s execution_id=%s ratecon_lifecycle_id=%s shipment_id=%s",

            task.id,

            execution_id,

            ratecon_workflow_lifecycle_id,

            shipment_id,

        )

        return EnqueueResult(

            enqueued=True,

            execution_id=execution_id,

            celery_task_id=task.id,

        )



    async def prepare_ratecon_completed_payload(

        self,

        *,

        tenant_id: str,

        tenant_slug: str,

        payload: dict[str, Any],

    ) -> PrepareResult:

        """Layer 2: validate parent ratecon state before driver lifecycle resolve."""

        tenant_settings = payload.get("tenant_settings") or {}

        missing = [

            key

            for key in _PREPARE_REQUIRED_KEYS

            if not self._clean(payload.get(key))

        ]

        if missing:

            raise Exception(

                f"Missing required payload keys for 'driver_assignment': {missing}"

            )



        out = dict(payload)

        thread_id = self._resolve_thread_id(tenant_id=tenant_id, payload=out)

        if thread_id:

            out["thread_id"] = thread_id



        self._ensure_pickup_on_payload(out)



        eligibility_skip = self._driver_request_skip_reason(out.get("shipment"))

        if eligibility_skip:

            logger.info(

                "driver_assignment prepare skipped reason=%s tenant_slug=%s shipment_id=%s",

                eligibility_skip,

                tenant_slug,

                out.get("shipment_id"),

            )

            return PrepareResult(skipped=True, skip_reason=eligibility_skip)



        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=out,

        )

        if skip_reason:

            logger.info(

                "driver_assignment prepare skipped reason=%s tenant_slug=%s shipment_id=%s",

                skip_reason,

                tenant_slug,

                out.get("shipment_id"),

            )

            return PrepareResult(skipped=True, skip_reason=skip_reason)



        return PrepareResult(skipped=False, payload=out)



    def check_start_eligibility(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        exclude_run_id: str | None = None,

    ) -> EligibilityResult:

        """Layer 3: idempotent in-graph gate before scheduling reminders."""

        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            eligibility_skip = self._driver_request_skip_reason(shipment)

            if eligibility_skip:

                return EligibilityResult(skip_reason=eligibility_skip)



        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=payload,

            require_process_enabled=False,

            exclude_run_id=exclude_run_id,

        )

        return EligibilityResult(skip_reason=skip_reason)



    def check_reminder_eligibility(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

    ) -> EligibilityResult:

        """Reminder_due gate: Turvo + driver-not-assigned only (no ratecon duplicate check)."""

        for key in ("thread_id", "load_id", "shipment_id", "shipments_row_id"):

            if not self._clean(payload.get(key)):

                return EligibilityResult(skip_reason="missing_correlation_keys")



        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            if driver_assigned_from_payload(shipment):

                return EligibilityResult(skip_reason="driver_already_assigned")

            eligibility_skip = self._driver_request_skip_reason(shipment)

            if eligibility_skip:

                return EligibilityResult(skip_reason=eligibility_skip)



        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        if shipments_row_id and self._driver_lifecycle_terminal(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

        ):

            return EligibilityResult(skip_reason="already_completed")



        lifecycle = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_id,

            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,

            shipment_id=shipments_row_id,

        ) if shipments_row_id else {}

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id")) if lifecycle else None

        if lifecycle_id:

            row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id)

            current_step = self._reminder_step_from_lifecycle_row(row)

            raw_step = payload.get("reminder_step")

            try:

                requested_step = int(raw_step) if raw_step is not None else None

            except (TypeError, ValueError):

                requested_step = None

            if requested_step is not None and requested_step <= current_step:

                return EligibilityResult(skip_reason="reminder_step_already_sent")



        return EligibilityResult(skip_reason=None)



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

        if not thread_id:

            return SendReminderResult(sent=False, error="missing_thread_id")



        settings = tenant_settings or {}

        account_id = self._clean(settings.get("mikey_account_id"))

        if not account_id:

            return SendReminderResult(sent=False, error="missing_mikey_account_id")



        reminder_step = payload.get("reminder_step")

        subject = self._clean(payload.get("subject"))

        if not subject:

            step_label = int(reminder_step) if reminder_step is not None else 0

            subject = f"Driver assignment reminder (step {step_label})"



        body = (str(payload.get("body") or "").strip()) or (

            "Please provide driver name and contact information for this load."

        )



        try:

            result = self._communications.send_thread_reply(

                tenant_id=tenant_id,

                thread_id=thread_id,

                body=body,

                account_id=account_id,

                subject=subject,

                workflow_run_id=workflow_run_id,

                communication_metadata={

                    "source": self._clean(payload.get("reminder_email_source"))

                    or "driver_assignment_reminder",

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



        success = True

        if isinstance(result, dict):

            success = bool(result.get("success", True))

        elif result is False:

            success = False

        if not success:

            return SendReminderResult(sent=False, error="send_failed")

        comm_id = None

        if isinstance(result, dict):

            comm_id = self._clean(result.get("communication_id"))

        return SendReminderResult(sent=True, error=None, communication_id=comm_id)



    @staticmethod

    def _reminder_step_from_lifecycle_row(row: dict[str, Any] | None) -> int:

        if not row:

            return 0

        sub = sub_status_type_from_db(row.get("sub_status"))

        mapping = {

            StatusSubType.REMINDER_1_SENT: 1,

            StatusSubType.REMINDER_2_SENT: 2,

            StatusSubType.REMINDER_3_SENT: 3,

            StatusSubType.REMINDER_4_SENT: 4,

        }

        return mapping.get(sub, 0)



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

        send_payload["body"] = _DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML

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



    @staticmethod

    def _has_in_reply_to(payload: dict[str, Any]) -> bool:

        val = payload.get("in_reply_to")

        if val is None:

            return False

        return bool(str(val).strip())



    def _build_driver_details_workflow_payload(

        self,

        *,

        tenant_uuid: str,

        tenant_slug: str,

        lifecycle_id: str,

        thread_id: str,

        payload: dict[str, Any],

        communication_id: str | None,

    ) -> dict[str, Any] | None:

        correlation = self._lifecycle_service.read_correlation_by_id(lifecycle_id)

        shipments_row_id = self._clean(

            (correlation or {}).get("shipment_id")

        )

        if not shipments_row_id:

            return None



        ship_row = self._shipments.get_by_id(

            tenant_id=tenant_uuid,

            shipment_id=shipments_row_id,

        )

        metadata = (ship_row or {}).get("metadata") or {}

        load_id = self._clean(metadata.get("load_id"))

        turvo_shipment_id = self._clean((ship_row or {}).get("shipment_number"))

        ratecon_lc = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_uuid,

            workflow_name=RATECON_WORKFLOW,

            shipment_id=shipments_row_id,

        )

        ratecon_workflow_lifecycle_id = self._clean(ratecon_lc.get("lifecycle_id"))

        if not all((load_id, turvo_shipment_id, ratecon_workflow_lifecycle_id)):

            return None



        return {

            "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            "tenant_id": tenant_uuid,

            "tenant_slug": tenant_slug,

            "workflow_lifecycle_id": lifecycle_id,

            "thread_id": thread_id,

            "shipments_row_id": shipments_row_id,

            "shipment_id": turvo_shipment_id,

            "load_id": load_id,

            "ratecon_workflow_lifecycle_id": ratecon_workflow_lifecycle_id,

            "communication_id": communication_id,

            "body": payload.get("body"),

            "subject": payload.get("subject"),

        }



    def enqueue_driver_assignment_event_and_link(

        self,

        *,

        tenant_uuid: str,

        tenant_slug: str,

        workflow_lifecycle_id: str,

        payload: dict[str, Any],

        event_type: str,

        communication_id: str | None = None,

        thread_id: str | None = None,

    ) -> str:

        execution_id = str(uuid.uuid4())

        body = {**payload, "event_type": event_type, "execution_id": execution_id}



        from app.tasks.workflows import run_workflow_async



        run_workflow_async.apply_async(

            kwargs={

                "tenant_slug": tenant_slug,

                "workflow_name": DRIVER_ASSIGNMENT_WORKFLOW,

                "payload": body,

            }

        )



        self._runs_service.record_workflow_run(

            run_id=execution_id,

            tenant_id=tenant_uuid,

            event_type=event_type,

            workflow_lifecycle_id=workflow_lifecycle_id,

        )



        if communication_id:

            self._communications.link_inbound_to_workflow_run(

                communication_id=communication_id,

                workflow_run_id=execution_id,

            )

        if thread_id:

            self._communications.link_workflow_run_to_thread(

                tenant_id=tenant_uuid,

                thread_id=thread_id,

                workflow_run_id=execution_id,

            )



        logger.info(

            "driver_assignment email queued execution_id=%s event_type=%s lifecycle_id=%s",

            execution_id,

            event_type,

            workflow_lifecycle_id,

        )

        return execution_id



    def try_driver_details_email_received(

        self,

        *,

        payload: dict[str, Any],

        tenant: UnipileTenantContext,

        communication_id: str | None = None,

    ) -> JSONResponse | None:

        if not self._has_in_reply_to(payload):

            return None



        thread_id = self._clean(payload.get("thread_id"))

        if not thread_id:

            return None



        tenant_row = TenantsService().get_by_slug(tenant.tenant_slug)

        tenant_settings = (tenant_row or {}).get("settings") or {}

        if not self._is_process_enabled(tenant_settings):

            return None



        lifecycle_id = self._communications.find_active_lifecycle_id_for_thread(

            tenant_id=tenant.tenant_uuid,

            thread_id=thread_id,

            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,

        )

        if not lifecycle_id:

            return None



        lifecycle_row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}

        sub = sub_status_type_from_db(lifecycle_row.get("sub_status"))

        if sub in (

            StatusSubType.DETAILS_RECEIVED,

            StatusSubType.UPLOADED_TO_TMS,

        ):

            return JSONResponse(

                status_code=status.HTTP_200_OK,

                content={

                    "message": "lifecycle terminal; driver details not processed",

                    "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

                    "workflow_lifecycle_id": lifecycle_id,

                },

            )



        workflow_payload = self._build_driver_details_workflow_payload(

            tenant_uuid=tenant.tenant_uuid,

            tenant_slug=tenant.tenant_slug,

            lifecycle_id=lifecycle_id,

            thread_id=thread_id,

            payload=payload,

            communication_id=communication_id,

        )

        if workflow_payload is None:

            logger.warning(

                "driver_details_email_received skipped missing correlation lifecycle_id=%s thread_id=%s",

                lifecycle_id,

                thread_id,

            )

            return None



        execution_id = self.enqueue_driver_assignment_event_and_link(

            tenant_uuid=tenant.tenant_uuid,

            tenant_slug=tenant.tenant_slug,

            workflow_lifecycle_id=lifecycle_id,

            payload=workflow_payload,

            event_type=WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            communication_id=communication_id,

            thread_id=thread_id,

        )

        return JSONResponse(

            status_code=status.HTTP_200_OK,

            content={

                "message": "success",

                "execution_id": execution_id,

                "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            },

        )





__all__ = (

    "DRIVER_ASSIGNMENT_WORKFLOW",

    "DriverAssignmentIngressService",

    "EligibilityResult",

    "EnqueueResult",

    "PrepareResult",

    "SendReminderResult",

)


