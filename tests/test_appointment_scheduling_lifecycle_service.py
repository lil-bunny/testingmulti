"""Appointment scheduling lifecycle service tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.domain.appointment_scheduling.metadata_keys import (
    EMAIL_DRAFT,
    LLM_APPOINTMENT_DECISION,
)
from app.services.appointment_scheduling.lifecycle_service import LifecycleService
from app.workflows.graph.routers import appointment_ingress_router, appointment_weekend_pickup_router
from app.domain.appointment_scheduling.metadata_hydration import normalize_appointment_state_data

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
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
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
        appointment_payload=scheduling_payload,
    )

    activity.record_draft_ready.assert_called_once_with(
        state,
        email_draft=email_draft,
        appointment_payload=scheduling_payload,
    )
    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={
            EMAIL_DRAFT: email_draft,
        },
    )
    shipments.update_proposed_appointments.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        proposed_pickup_at="2026-07-30",
        proposed_delivery_at="08/04/2026",
        proposed_pickup_time=None,
        proposed_delivery_time=None,
        pickup_timezone="America/Chicago",
        delivery_timezone="America/Los_Angeles",
    )
    shipments.get_by_id.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_id=_SHIPMENT_ROW_ID,
    )
    shipments.merge_metadata.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        metadata_patch={"reference_number": "DIAMOND-1"},
    )
    lifecycle.update_lifecycle_status.assert_not_called()


def test_persist_draft_ready_patches_llm_scheduling_decision():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    email_draft = {"to": "a@example.com", "cc": [], "subject": "subj", "full_html": "<html/>"}
    scheduling_payload = {"proposed_pickup_at": "2026-07-30", "proposed_delivery_at": "08/04/2026"}
    decision = {
        "weekend_shifted": True,
        "selected_pickup_date": "2026-07-01",
        "selected_pickup_time": "08:00",
    }
    state = _state()

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft=email_draft,
        appointment_payload=scheduling_payload,
        llm_appointment_decision=decision,
    )

    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={
            EMAIL_DRAFT: email_draft,
            LLM_APPOINTMENT_DECISION: decision,
        },
    )


def test_persist_draft_ready_passes_llm_pickup_and_costco_delivery_time():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    scheduling_payload = {
        "proposed_pickup_at": "2026-07-30",
        "proposed_delivery_at": "08/04/2026",
    }
    state = _state(customer_name="COSTCO #584 NW")

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft={"to": "a@example.com", "cc": [], "subject": "s", "full_html": "<p/>"},
        appointment_payload=scheduling_payload,
        llm_appointment_decision={"selected_pickup_time": "08:30"},
    )

    shipments.update_proposed_appointments.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        proposed_pickup_at="2026-07-30",
        proposed_delivery_at="08/04/2026",
        proposed_pickup_time="08:30",
        proposed_delivery_time="06:00",
        pickup_timezone="America/Chicago",
        delivery_timezone="America/Los_Angeles",
    )


def test_persist_draft_ready_merges_po_number_when_resolved():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    turvo_payload = {
        "details": {
            "globalRoute": [
                {"stopType": {"value": "Pickup"}, "deleted": False},
                {
                    "stopType": {"value": "Delivery"},
                    "poNumbers": "006900520275",
                    "deleted": False,
                },
            ]
        }
    }
    state = _state(
        customer_name="Costco Wholesale",
        shipment=turvo_payload,
        pickup_dropoff_data={"po_number": "IGNORED"},
    )

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft={"to": "a@example.com", "cc": [], "subject": "s", "full_html": "<p/>"},
        appointment_payload={"proposed_pickup_at": "2026-07-30", "proposed_delivery_at": "08/04/2026"},
    )

    shipments.merge_metadata.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        metadata_patch={"po_number": "006900520275"},
    )


def test_persist_draft_ready_skips_merge_when_po_empty():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    state = _state(
        customer_name="Other Customer",
        pickup_dropoff_data={},
    )

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft={"to": "a@example.com", "cc": [], "subject": "s", "full_html": "<p/>"},
        appointment_payload={"proposed_pickup_at": "2026-07-30", "proposed_delivery_at": "08/04/2026"},
    )

    shipments.merge_metadata.assert_not_called()


def test_persist_draft_ready_non_costco_uses_ascend_pickup_po():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    state = _state(
        customer_name="Diamond Pet Foods",
        pickup_dropoff_data={"po_number": "A1165831"},
    )

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft={"to": "a@example.com", "cc": [], "subject": "s", "full_html": "<p/>"},
        appointment_payload={"proposed_pickup_at": "2026-07-30", "proposed_delivery_at": "08/04/2026"},
    )

    shipments.merge_metadata.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        metadata_patch={"po_number": "A1165831"},
    )


def test_persist_draft_ready_merges_reference_number_to_shipment_metadata():
    lifecycle = MagicMock()
    activity = MagicMock()
    shipments = MagicMock()
    shipments.update_proposed_appointments.return_value = True
    shipments.get_by_id.return_value = {
        "pickup_timezone": "America/Chicago",
        "delivery_timezone": "America/Los_Angeles",
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
        shipments_service=shipments,
    )
    state = _state(
        customer_name="Diamond Pet Foods",
        load_id="30381",
        draft_static={"commodity": "DIAMOND PET FOODS"},
        pickup_dropoff_data={"pallet_count": 28},
    )

    service.persist_draft_ready(
        state,
        lifecycle_id="lifecycle-1",
        email_draft={"to": "a@example.com", "cc": [], "subject": "s", "full_html": "<p/>"},
        appointment_payload={
            "reference_number": "DIAMOND-RPN00008809",
            "proposed_pickup_at": "2026-07-30",
            "proposed_delivery_at": "08/04/2026",
        },
    )

    shipments.merge_metadata.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENT_ROW_ID,
        metadata_patch={
            "reference_number": "DIAMOND-RPN00008809",
            "load_id": "30381",
            "pallet_count": 28,
            "commodity": "DIAMOND PET FOODS",
        },
    )


def test_mark_restartable_skip_delegates_to_mark_failed() -> None:
    from app.domain.appointment_scheduling.failure import SchedulingFailure
    from app.domain.appointment_scheduling.metadata_keys import APPOINTMENT_FAILURE_REASON
    from app.domain.error_catalog import SystemError

    lifecycle = MagicMock()
    activity = MagicMock()
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
    )

    service.mark_restartable_skip(
        "lifecycle-1",
        "enqueue_failed",
        tenant_id=_TENANT_UUID,
        workflow_run_id=_RUN_UUID,
    )

    activity.record_failed.assert_called_once()
    failure_arg: SchedulingFailure = activity.record_failed.call_args.kwargs["failure"]
    assert failure_arg.code == SystemError.UNEXPECTED_NODE_FAILURE.value
    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={
            APPOINTMENT_FAILURE_REASON: SystemError.UNEXPECTED_NODE_FAILURE.value,
        },
    )


def test_mark_failed_delegates_activity_and_patches_metadata():
    from app.domain.appointment_scheduling.failure import SchedulingFailure
    from app.domain.appointment_scheduling.metadata_keys import APPOINTMENT_FAILURE_REASON
    from app.domain.error_catalog import BusinessError, format_error_message

    lifecycle = MagicMock()
    activity = MagicMock()
    service = LifecycleService(
        lifecycle_service=lifecycle,
        activity_service=activity,
    )
    failure = SchedulingFailure.from_catalog(
        BusinessError.MISSING_RECIPIENT_EMAIL,
        format_error_message(BusinessError.MISSING_RECIPIENT_EMAIL, customer_name="Acme"),
    )

    service.mark_failed(
        "lifecycle-1",
        failure,
        tenant_id=_TENANT_UUID,
        workflow_run_id=_RUN_UUID,
    )

    activity.record_failed.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id="lifecycle-1",
        workflow_run_id=_RUN_UUID,
        failure=failure,
    )
    lifecycle.patch_metadata.assert_called_once_with(
        lifecycle_id="lifecycle-1",
        metadata_patch={
            APPOINTMENT_FAILURE_REASON: BusinessError.MISSING_RECIPIENT_EMAIL.value,
        },
    )
    lifecycle.update_lifecycle_status.assert_not_called()


def test_hydrate_appointment_send_context_maps_portal_shipment_uuid_to_turvo_id():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "metadata": {
            EMAIL_DRAFT: {
                "to": "a@example.com",
                "subject": "DEL APPT REQ \"30381\"",
                "full_html": "<html/>",
            },
        },
    }
    lifecycle.read_correlation_by_id.return_value = {"shipment_id": _SHIPMENT_ROW_ID}
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1000324895",
        "metadata": {"reference_number": "DIAMOND-RPN00008809"},
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )
    portal_shipment_uuid = _SHIPMENT_ROW_ID
    state = _state(
        shipment_id=portal_shipment_uuid,
        shipments_row_id="",
    )

    service.hydrate_appointment_send_context(state)

    assert state.data["email_draft"]["subject"] == 'DEL APPT REQ "30381"'
    assert state.data["reference_number"] == "DIAMOND-RPN00008809"
    assert state.data["shipments_row_id"] == _SHIPMENT_ROW_ID
    assert state.data["shipment_id"] == "1000324895"
    assert state.data["appointment_payload"]["reference_number"] == "DIAMOND-RPN00008809"
    assert shipments.get_by_id.call_count == 2


def test_hydrate_appointment_send_context_keeps_turvo_id_when_shipments_row_already_in_state():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "metadata": {EMAIL_DRAFT: {"to": "a@example.com", "subject": "s", "full_html": "<p/>"}},
    }
    shipments = MagicMock()
    shipments.get_by_id.return_value = {"shipment_number": "1000324895"}
    service = LifecycleService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )
    state = _state(shipment_id=_SHIPMENT_ROW_ID, shipments_row_id=_SHIPMENT_ROW_ID)

    service.hydrate_appointment_send_context(state)

    assert state.data["shipment_id"] == "1000324895"
    lifecycle.read_correlation_by_id.assert_not_called()


def test_legacy_checkpoint_llm_decision_routes_after_normalize() -> None:
    state = _state(
        event_type="appointment_draft_send",
        shipments_row_id=_SHIPMENT_ROW_ID,
    )
    state.data["llm_scheduling_decision"] = {
        "weekend_shifted": True,
        "selected_pickup_date": "2026-07-01",
    }
    normalize_appointment_state_data(state.data)
    assert state.data["llm_appointment_decision"]["weekend_shifted"] is True
    assert appointment_weekend_pickup_router(state) == "apply"


def test_legacy_checkpoint_ingress_skip_routes_after_normalize() -> None:
    state = _state()
    state.data["scheduling_prepare_skip_reason"] = "duplicate_event"
    normalize_appointment_state_data(state.data)
    assert state.data["appointment_ingress_skip_reason"] == "duplicate_event"
    assert appointment_ingress_router(state) == "end"


def test_hydrate_appointment_send_context_restores_llm_scheduling_decision_for_send_path():
    decision = {
        "weekend_shifted": True,
        "selected_pickup_date": "2026-07-01",
        "selected_pickup_time": "08:00",
    }
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "metadata": {
            EMAIL_DRAFT: {
                "to": "a@example.com",
                "subject": "DEL APPT",
                "full_html": "<html/>",
            },
            LLM_APPOINTMENT_DECISION: decision,
        },
    }
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1000324895",
        "metadata": {"reference_number": "DIAMOND-RPN1"},
    }
    service = LifecycleService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )
    state = _state(
        event_type="appointment_draft_send",
        shipments_row_id=_SHIPMENT_ROW_ID,
    )

    service.hydrate_appointment_send_context(state)

    assert state.data["llm_appointment_decision"] == decision
    assert appointment_weekend_pickup_router(state) == "apply"


def test_hydrate_appointment_send_context_weekend_router_skips_without_decision():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "metadata": {
            EMAIL_DRAFT: {
                "to": "a@example.com",
                "subject": "DEL APPT",
                "full_html": "<html/>",
            },
        },
    }
    shipments = MagicMock()
    shipments.get_by_id.return_value = {"shipment_number": "1000324895"}
    service = LifecycleService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )
    state = _state(
        event_type="appointment_draft_send",
        shipments_row_id=_SHIPMENT_ROW_ID,
    )

    service.hydrate_appointment_send_context(state)

    assert "llm_appointment_decision" not in state.data
    assert appointment_weekend_pickup_router(state) == "skip"


def test_hydrate_read_context_sets_status_and_draft_without_full_metadata():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "pending_review",
        "sub_status": "appointment_draft_created",
        "metadata": {
            EMAIL_DRAFT: {
                "to": "a@example.com",
                "subject": "DEL APPT",
                "full_html": "<html/>",
            },
            LLM_APPOINTMENT_DECISION: {"weekend_shifted": False},
        },
    }
    service = LifecycleService(lifecycle_service=lifecycle)
    state = _state(event_type="appointment_draft_send")

    service.hydrate_read_context(state)

    assert state.data["workflow_lifecycle_status"] == "pending_review"
    assert state.data["workflow_lifecycle_sub_status"] == "appointment_draft_created"
    assert state.data["email_draft"]["to"] == "a@example.com"
    assert "workflow_lifecycle_row" not in state.data
    assert "workflow_lifecycle_metadata" not in state.data
    assert "llm_appointment_decision" not in state.data


def test_hydrate_appointment_send_context_does_not_set_workflow_lifecycle_metadata():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "metadata": {
            EMAIL_DRAFT: {"to": "a@example.com", "subject": "s", "full_html": "<p/>"},
            LLM_APPOINTMENT_DECISION: {"weekend_shifted": False},
        },
    }
    shipments = MagicMock()
    shipments.get_by_id.return_value = {"shipment_number": "1000324895"}
    service = LifecycleService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )
    state = _state(shipments_row_id=_SHIPMENT_ROW_ID)

    service.hydrate_appointment_send_context(state)

    assert "workflow_lifecycle_metadata" not in state.data
    assert state.data["llm_appointment_decision"] == {"weekend_shifted": False}
