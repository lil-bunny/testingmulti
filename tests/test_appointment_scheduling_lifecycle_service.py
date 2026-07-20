"""Appointment scheduling lifecycle service tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.domain.appointment_scheduling.metadata_keys import EMAIL_DRAFT, SCHEDULING_PAYLOAD
from app.services.appointment_scheduling.lifecycle_service import AppointmentSchedulingLifecycleService

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_RUN_UUID = "22222222-3333-4444-5555-666666666666"
_SHIPMENT_ROW_ID = "33333333-4444-5555-6666-777777777777"


def _state(**data_overrides):
    data = {
        "workflow_lifecycle_id": "lifecycle-1",
        "tenant_id": _TENANT_UUID,
        "shipments_row_id": _SHIPMENT_ROW_ID,
    }
    data.update(data_overrides)
    return SimpleNamespace(
        tenant_id=_TENANT_UUID,
        execution_id=_RUN_UUID,
        data=data,
    )


def test_persist_draft_ready_delegates_activity_patches_metadata_and_shipment():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    service = AppointmentSchedulingLifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    email_draft = {"to": "a@example.com", "cc": [], "subject": "subj", "full_html": "<html/>"}
    scheduling_payload = {
        "reference_number": "DIAMOND-1",
        "shipment_details": "details",
        "proposed_pickup_at": "2026-07-30",
        "proposed_delivery_at": "08/04/2026",
    }
    state = _state()

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft=email_draft,
        scheduling_payload=scheduling_payload,
    )

    activity.record_draft_ready.assert_called_once_with(
        state,
        email_draft=email_draft,
        scheduling_payload=scheduling_payload,
    )
    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={
            EMAIL_DRAFT: email_draft,
            SCHEDULING_PAYLOAD: scheduling_payload,
        },
    )
    shipments.update_proposed_appointments.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        proposed_pickup_at="2026-07-30",
        proposed_delivery_at="08/04/2026",
    )
    lifecycle.update_lifecycle_status.assert_not_called()


def test_mark_failed_delegates_activity_and_patches_metadata():
    lifecycle = MagicMock()
    activity = MagicMock()
    service = AppointmentSchedulingLifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
    )

    service.mark_failed(
        "lifecycle-1",
        "missing_recipient_email",
        tenant_id=_TENANT_UUID,
        workflow_run_id=_RUN_UUID,
    )

    activity.record_failed.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id="lifecycle-1",
        workflow_run_id=_RUN_UUID,
        reason="missing_recipient_email",
    )
    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={"scheduling_failure_reason": "missing_recipient_email"},
    )
    lifecycle.update_lifecycle_status.assert_not_called()
