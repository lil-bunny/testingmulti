"""RateconSupersedeService unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.domain.workflow_cancel_trigger import RATECON_SUPERSEDED_TRIGGER
from app.services.ratecon_supersede_service import RateconSupersedeService
from app.services.workflow_lifecycle_cancel_service import WorkflowCancelResult

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_SHIPMENTS_ROW_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_supersede_before_run_skips_when_comm_already_linked() -> None:
    comms = MagicMock()
    comms.is_communication_linked_to_run.return_value = True
    orchestrator = MagicMock()
    svc = RateconSupersedeService(
        orchestrator=orchestrator,
        communications=comms,
    )

    result = svc.supersede_before_run(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        shipments_row_id=_SHIPMENTS_ROW_ID,
        load_id="30389",
        shipment_id="1000324895",
        communication_id="comm-1",
    )

    assert result == {}
    orchestrator.cancel_for_trigger.assert_not_called()
    comms.is_communication_linked_to_run.assert_called_once_with(
        communication_id="comm-1",
    )


def test_supersede_before_run_calls_orchestrator() -> None:
    comms = MagicMock()
    comms.is_communication_linked_to_run.return_value = False
    orchestrator = MagicMock()
    orchestrator.cancel_for_trigger.return_value = {
        "ratecon": WorkflowCancelResult(
            cancelled=True,
            lifecycle_id="ratecon-old",
        ),
        "driver_assignment": WorkflowCancelResult(
            cancelled=False,
            skip_reason="no_active_lifecycle",
        ),
    }
    svc = RateconSupersedeService(
        orchestrator=orchestrator,
        communications=comms,
    )

    results = svc.supersede_before_run(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        shipments_row_id=_SHIPMENTS_ROW_ID,
        load_id="30389",
        shipment_id="1000324895",
    )

    assert results["ratecon"].cancelled is True
    orchestrator.cancel_for_trigger.assert_called_once()
    trigger = orchestrator.cancel_for_trigger.call_args.args[0]
    assert trigger.trigger == RATECON_SUPERSEDED_TRIGGER
    assert trigger.shipments_row_id == _SHIPMENTS_ROW_ID
    assert trigger.load_id == "30389"


def test_supersede_before_run_logs_driver_assignment_cancelled() -> None:
    comms = MagicMock()
    comms.is_communication_linked_to_run.return_value = False
    orchestrator = MagicMock()
    orchestrator.cancel_for_trigger.return_value = {
        "ratecon": WorkflowCancelResult(
            cancelled=True,
            lifecycle_id="ratecon-old",
        ),
        "driver_assignment": WorkflowCancelResult(
            cancelled=True,
            lifecycle_id="da-old",
        ),
    }
    svc = RateconSupersedeService(
        orchestrator=orchestrator,
        communications=comms,
    )

    results = svc.supersede_before_run(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        shipments_row_id=_SHIPMENTS_ROW_ID,
        load_id="30389",
        shipment_id="1000324895",
    )

    assert results["driver_assignment"].cancelled is True
    assert results["driver_assignment"].lifecycle_id == "da-old"


def test_ratecon_ingress_prepare_payload_calls_supersede() -> None:
    from app.services.ratecon_ingress_service import RateconIngressService

    shipments = MagicMock()
    shipments.upsert_from_load_id = AsyncMock(
        return_value={
            "success": True,
            "shipments_row_id": _SHIPMENTS_ROW_ID,
            "shipment_number": "1000324895",
        }
    )
    supersede = MagicMock()
    ingress = RateconIngressService(
        shipments_service=shipments,
        supersede_service=supersede,
    )

    import asyncio

    out = asyncio.run(
        ingress.prepare_payload(
            tenant_id=_TENANT_ID,
            tenant_slug="t3ra",
            payload={"load_id": "30389", "communication_id": "comm-new"},
        )
    )

    assert out["shipments_row_id"] == _SHIPMENTS_ROW_ID
    supersede.supersede_before_run.assert_called_once_with(
        tenant_id=_TENANT_ID,
        tenant_slug="t3ra",
        shipments_row_id=_SHIPMENTS_ROW_ID,
        load_id="30389",
        shipment_id="1000324895",
        communication_id="comm-new",
    )


def test_ratecon_ingress_prepare_payload_raises_shipment_not_found_in_tms() -> None:
    import asyncio

    import pytest

    from app.domain.error_catalog import BusinessError
    from app.exceptions import WorkflowException
    from app.services.ratecon_ingress_service import RateconIngressService

    shipments = MagicMock()
    shipments.upsert_from_load_id = AsyncMock(
        return_value={"success": False, "message": "turvo_shipment_not_found"}
    )
    ingress = RateconIngressService(
        shipments_service=shipments,
        supersede_service=MagicMock(),
    )

    with pytest.raises(WorkflowException) as exc_info:
        asyncio.run(
            ingress.prepare_payload(
                tenant_id=_TENANT_ID,
                tenant_slug="t3ra",
                payload={"load_id": "30389"},
            )
        )

    err = exc_info.value
    assert err.error_code == BusinessError.SHIPMENT_NOT_FOUND_IN_TMS.value
    assert err.error_category == BusinessError.CATEGORY
    assert err.message == BusinessError.SHIPMENT_NOT_FOUND_IN_TMS.description
