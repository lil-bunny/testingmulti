"""Escalate driver assignment to internal Teams when carrier details are missing."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from app.core.logger import get_logger
from app.domain.driver_assignment.escalation import (
    DriverEscalationDisplayFields,
    driver_escalation_facts,
    format_driver_escalation_body,
    format_driver_escalation_title,
    parse_driver_assignment_escalate_settings,
    skip_sub_statuses_from_driver_assignment_settings,
)
from app.domain.driver_assignment.guards import blocks_driver_assignment_escalation
from app.integrations.teams.webhook import TeamsWebhookError, post_message_card
from app.integrations.turvo.shipments import (
    driver_assigned_from_payload,
    pickup_appointment_from_payload,
    shipment_display_fields_from_payload,
)
from app.services.driver_assignment.activity_service import DriverAssignmentActivityService
from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

logger = get_logger(__name__)


@dataclass(frozen=True)
class EscalationResult:
    sent: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None


class DriverAssignmentEscalationService:
    def __init__(
        self,
        *,
        ingress_service: DriverAssignmentIngressService | None = None,
        activity_service: DriverAssignmentActivityService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._ingress = ingress_service or DriverAssignmentIngressService()
        self._activity = activity_service or DriverAssignmentActivityService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    def escalate_from_payload(
        self,
        *,
        tenant_id: str,
        tenant_settings: dict[str, Any] | None,
        payload: dict[str, Any],
        workflow_run_id: str | None = None,
    ) -> EscalationResult:
        eligibility = self._ingress.check_escalation_eligibility(
            tenant_id=tenant_id,
            payload=payload,
        )
        if eligibility.skip_reason:
            logger.info(
                "driver escalation skipped lifecycle_id=%s reason=%s",
                payload.get("workflow_lifecycle_id"),
                eligibility.skip_reason,
            )
            return EscalationResult(skipped=True, skip_reason=eligibility.skip_reason)

        settings = parse_driver_assignment_escalate_settings(tenant_settings)
        if settings is None:
            return EscalationResult(error="invalid_escalate_driver_settings")

        wl_id = str(payload.get("workflow_lifecycle_id") or "").strip()
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id) if wl_id else None
        skip_subs = skip_sub_statuses_from_driver_assignment_settings(tenant_settings)
        skip = delayed_workflow_step_skip_reason(row, skip_sub_statuses=skip_subs)
        if skip:
            return EscalationResult(skipped=True, skip_reason=skip)
        if blocks_driver_assignment_escalation(row):
            return EscalationResult(skipped=True, skip_reason="already_completed")

        fields = self._display_fields(payload, row)
        title = format_driver_escalation_title(settings.message_title, fields=fields)
        body = format_driver_escalation_body(settings.message_body, fields=fields)
        facts = driver_escalation_facts(fields)

        # ponytail: Teams stays live in workflow shadow_mode (email/Turvo are gated elsewhere)
        try:
            asyncio.run(
                post_message_card(
                    settings.teams_webhook_url,
                    title=title,
                    text=body,
                    facts=facts,
                )
            )
        except TeamsWebhookError as exc:
            logger.warning(
                "driver escalation Teams post failed lifecycle_id=%s status=%s",
                wl_id,
                exc.status_code,
            )
            return EscalationResult(error="teams_post_failed")

        state = SimpleNamespace(
            data=dict(payload),
            tenant_id=tenant_id,
            execution_id=workflow_run_id,
        )
        self._activity.record_escalation_sent(state)
        return EscalationResult(sent=True)

    @staticmethod
    def _display_fields(
        payload: dict[str, Any],
        lifecycle_row: dict[str, Any] | None,
    ) -> DriverEscalationDisplayFields:
        shipment = payload.get("shipment") if isinstance(payload.get("shipment"), dict) else {}
        display = shipment_display_fields_from_payload(shipment)
        pickup = pickup_appointment_from_payload(shipment)
        pickup_at = ""
        pickup_tz = str(payload.get("pickup_appointment_timezone") or "").strip()
        if pickup is not None:
            pickup_at = pickup.at_utc.isoformat()
            if pickup.timezone:
                pickup_tz = pickup.timezone
        elif payload.get("pickup_appointment_at"):
            pickup_at = str(payload.get("pickup_appointment_at")).strip()

        delivery = ""
        if display.delivery_date is not None:
            delivery = display.delivery_date.isoformat()

        sub_status = ""
        if lifecycle_row:
            sub_status = str(lifecycle_row.get("sub_status") or "").strip()

        return DriverEscalationDisplayFields(
            load_id=str(payload.get("load_id") or "").strip(),
            shipment_id=str(payload.get("shipment_id") or "").strip(),
            shipments_row_id=str(payload.get("shipments_row_id") or "").strip(),
            workflow_lifecycle_id=str(payload.get("workflow_lifecycle_id") or "").strip(),
            carrier_name=str(display.carrier_name or "").strip(),
            customer_name=str(display.customer_name or "").strip(),
            delivery_date=delivery,
            pickup_at=pickup_at,
            pickup_timezone=pickup_tz,
            current_sub_status=sub_status,
        )
