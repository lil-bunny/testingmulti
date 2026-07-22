"""Tests for appointment scheduling customer reply ingress."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.ingress_result import IngressResult
from app.models.status import StatusSubType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.customer_reply_ingress import (
    AppointmentCustomerReplyIngressService,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext

_TENANT = UnipileTenantContext(tenant_uuid="tenant-1", tenant_slug="t3ra")
_THREAD = "thread-abc"
_LC = "lifecycle-1"


def _enabled_settings() -> dict:
    return {"enabledProcesses": ["appointment_scheduling"]}


def _reply_payload() -> dict:
    return {
        "thread_id": _THREAD,
        "in_reply_to": "prior-msg",
        "body": "Delivery confirmed July 18 at 10:30 AM",
    }


def _service(**overrides) -> AppointmentCustomerReplyIngressService:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "id": _LC,
        "status": "pending_review",
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
        "metadata": {"reference_number": "DIAMOND-1", "customer_name": "Costco"},
    }
    lifecycle.read_correlation_by_id.return_value = {"shipment_id": "ship-row-1"}
    lifecycle.find_awaiting_customer_reply_lifecycle_id.return_value = None
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.return_value = None
    comms = MagicMock()
    comms.find_active_lifecycle_id_for_thread.return_value = _LC
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1001",
        "metadata": {"load_id": "load-1"},
    }
    runs = MagicMock()
    svc = AppointmentCustomerReplyIngressService(
        lifecycle_service=lifecycle,
        communications_service=comms,
        shipments_service=shipments,
        runs_service=runs,
        process_enabled_check=lambda _s: True,
    )
    for key, value in overrides.items():
        setattr(svc, key, value)
    return svc


def test_try_customer_reply_enqueues_when_lifecycle_active() -> None:
    svc = _service()
    with patch.dict("sys.modules", {"app.tasks.workflows": MagicMock()}):
        import sys

        sys.modules["app.tasks.workflows"].run_workflow_async.apply_async = MagicMock()
        with patch(
            "app.services.tenants_service.TenantsService.get_by_slug",
            return_value={"settings": _enabled_settings()},
        ):
            result = svc.try_customer_reply_received(
                payload=_reply_payload(),
                tenant=_TENANT,
                communication_id="comm-1",
            )

    assert isinstance(result, IngressResult)
    assert result.outcome == "enqueued"
    assert result.event_type == WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value


def test_try_customer_reply_skips_when_not_reply() -> None:
    svc = _service()
    result = svc.try_customer_reply_received(
        payload={"thread_id": _THREAD, "body": "hello"},
        tenant=_TENANT,
        communication_id="comm-1",
    )
    assert result is None


def test_try_customer_reply_enqueues_via_subject_fallback_when_thread_miss() -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "id": _LC,
        "status": "pending_review",
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
        "metadata": {"reference_number": "DIAMOND-1", "customer_name": "Costco"},
    }
    lifecycle.read_correlation_by_id.return_value = {"shipment_id": "ship-row-1"}
    lifecycle.find_awaiting_customer_reply_lifecycle_id.return_value = None
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.return_value = _LC
    comms = MagicMock()
    comms.find_active_lifecycle_id_for_thread.return_value = None
    comms.find_shipment_context_for_thread.return_value = []
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1001",
        "metadata": {"load_id": "63294"},
    }
    svc = AppointmentCustomerReplyIngressService(
        lifecycle_service=lifecycle,
        communications_service=comms,
        shipments_service=shipments,
        runs_service=MagicMock(),
        process_enabled_check=lambda _s: True,
    )

    with patch.dict("sys.modules", {"app.tasks.workflows": MagicMock()}):
        import sys

        sys.modules["app.tasks.workflows"].run_workflow_async.apply_async = MagicMock()
        with patch(
            "app.services.tenants_service.TenantsService.get_by_slug",
            return_value={"settings": _enabled_settings()},
        ):
            result = svc.try_customer_reply_received(
                payload={
                    **_reply_payload(),
                    "subject": 'Re: DEL APPT REQ "63294"',
                },
                tenant=_TENANT,
                communication_id="comm-1",
            )

    assert isinstance(result, IngressResult)
    assert result.outcome == "enqueued"
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.assert_called_once_with(
        tenant_id=_TENANT.tenant_uuid,
        subject_token="63294",
    )


def test_try_customer_reply_enqueues_via_costco_rpn_subject_fallback() -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "id": _LC,
        "status": "pending_review",
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
        "metadata": {
            "scheduling_payload": {"reference_number": "DIAMOND-RPN00006732"},
        },
    }
    lifecycle.read_correlation_by_id.return_value = {"shipment_id": "ship-row-1"}
    lifecycle.find_awaiting_customer_reply_lifecycle_id.return_value = None
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.return_value = _LC
    comms = MagicMock()
    comms.find_active_lifecycle_id_for_thread.return_value = None
    comms.find_shipment_context_for_thread.return_value = []
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1000338217",
        "metadata": {
            "load_id": "30394",
            "reference_number": "DIAMOND-RPN00006732",
        },
    }
    svc = AppointmentCustomerReplyIngressService(
        lifecycle_service=lifecycle,
        communications_service=comms,
        shipments_service=shipments,
        runs_service=MagicMock(),
        process_enabled_check=lambda _s: True,
    )

    with patch.dict("sys.modules", {"app.tasks.workflows": MagicMock()}):
        import sys

        sys.modules["app.tasks.workflows"].run_workflow_async.apply_async = MagicMock()
        with patch(
            "app.services.tenants_service.TenantsService.get_by_slug",
            return_value={"settings": _enabled_settings()},
        ):
            result = svc.try_customer_reply_received(
                payload={
                    **_reply_payload(),
                    "subject": 'Re: DEL APPT REQ "DIAMOND-RPN00006732"',
                },
                tenant=_TENANT,
                communication_id="comm-1",
            )

    assert isinstance(result, IngressResult)
    assert result.outcome == "enqueued"
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.assert_called_once_with(
        tenant_id=_TENANT.tenant_uuid,
        subject_token="DIAMOND-RPN00006732",
    )


def test_try_customer_reply_skips_when_thread_and_subject_miss() -> None:
    lifecycle = MagicMock()
    lifecycle.find_awaiting_customer_reply_lifecycle_id.return_value = None
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.return_value = None
    comms = MagicMock()
    comms.find_active_lifecycle_id_for_thread.return_value = None
    comms.find_shipment_context_for_thread.return_value = []
    svc = AppointmentCustomerReplyIngressService(
        lifecycle_service=lifecycle,
        communications_service=comms,
        shipments_service=MagicMock(),
        runs_service=MagicMock(),
        process_enabled_check=lambda _s: True,
    )

    with patch(
        "app.services.tenants_service.TenantsService.get_by_slug",
        return_value={"settings": _enabled_settings()},
    ):
        result = svc.try_customer_reply_received(
            payload={
                **_reply_payload(),
                "subject": "Re: unrelated subject",
            },
            tenant=_TENANT,
            communication_id="comm-1",
        )

    assert result is None
    lifecycle.find_awaiting_customer_reply_by_appt_subject_token.assert_not_called()


def test_build_reply_workflow_payload_uses_shipment_customer_name_column() -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {"metadata": {}}
    lifecycle.read_correlation_by_id.return_value = {"shipment_id": "ship-row-1"}
    shipments = MagicMock()
    shipments.get_by_id.return_value = {
        "shipment_number": "1000315335",
        "customer_name": "Costco Wholesale",
        "metadata": {"load_id": "63294", "reference_number": "DIAMOND-RPN-1"},
    }
    svc = AppointmentCustomerReplyIngressService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )

    payload = svc.build_reply_workflow_payload(
        tenant_uuid="tenant-1",
        tenant_slug="t3ra",
        lifecycle_id=_LC,
        thread_id=_THREAD,
        payload={"body": "confirmed", "subject": 'Re: DEL APPT REQ "63294"'},
        communication_id="comm-1",
    )

    assert payload is not None
    assert payload["customer_name"] == "Costco Wholesale"
