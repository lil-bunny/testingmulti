"""DriverAssignmentShipmentDetailsService — persist guards and delegation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.driver_assignment.shipment_driver_details_service import (
    DriverAssignmentShipmentDetailsService,
)
from app.tools.driver_details import DO_NOTHING, HAS_DETAILS, INSUFFICIENT

_TENANT = "00000000-0000-4000-8000-0000000000e1"
_SHIP_ROW = "00000000-0000-4000-8000-0000000000s1"


def _state(**data):
    return SimpleNamespace(tenant_id=_TENANT, data={"tenant_id": _TENANT, "shipments_row_id": _SHIP_ROW, **data})


def test_persist_extracted_skips_do_nothing() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_extracted_from_state(
        _state(driver_details_decision=DO_NOTHING, driver_details_extraction={"driver": {"name": "John"}})
    )
    shipments.merge_driver_details.assert_not_called()


def test_persist_extracted_skips_when_no_name_or_phone() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_extracted_from_state(
        _state(
            driver_details_decision=INSUFFICIENT,
            driver_details_extraction={"driver": {"name": None, "phone": None}},
        )
    )
    shipments.merge_driver_details.assert_not_called()


def test_persist_extracted_merges_name_only() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_extracted_from_state(
        _state(
            driver_details_decision=INSUFFICIENT,
            driver_details_extraction={"driver": {"name": "John", "phone": None}},
        )
    )
    shipments.merge_driver_details.assert_called_once_with(
        tenant_id=_TENANT,
        shipment_row_id=_SHIP_ROW,
        name="John",
        phone=None,
    )


def test_persist_extracted_merges_has_details() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_extracted_from_state(
        _state(
            driver_details_decision=HAS_DETAILS,
            driver_details_extraction={"driver": {"name": "Jane", "phone": "555-0100"}},
        )
    )
    shipments.merge_driver_details.assert_called_once_with(
        tenant_id=_TENANT,
        shipment_row_id=_SHIP_ROW,
        name="Jane",
        phone="555-0100",
    )


def test_persist_tms_matched_prefers_tms_fields() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_tms_matched_from_state(
        _state(
            tms_matched_driver_name="TMS Name",
            tms_matched_driver_phone="999-0000",
            driver_details_extraction={"driver": {"name": "Email Name", "phone": "111"}},
        )
    )
    shipments.merge_driver_details.assert_called_once_with(
        tenant_id=_TENANT,
        shipment_row_id=_SHIP_ROW,
        name="TMS Name",
        phone="999-0000",
    )


def test_persist_tms_matched_falls_back_to_extraction() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    svc.persist_tms_matched_from_state(
        _state(driver_details_extraction={"driver": {"name": "John", "phone": "555"}})
    )
    shipments.merge_driver_details.assert_called_once_with(
        tenant_id=_TENANT,
        shipment_row_id=_SHIP_ROW,
        name="John",
        phone="555",
    )


def test_persist_extracted_logs_and_skips_missing_scope() -> None:
    shipments = MagicMock()
    svc = DriverAssignmentShipmentDetailsService(shipments_service=shipments)
    state = SimpleNamespace(
        tenant_id="",
        data={
            "driver_details_decision": HAS_DETAILS,
            "driver_details_extraction": {"driver": {"name": "John", "phone": None}},
        },
    )
    with patch(
        "app.services.driver_assignment.shipment_driver_details_service.logger"
    ) as log:
        svc.persist_extracted_from_state(state)
    shipments.merge_driver_details.assert_not_called()
    log.warning.assert_called_once()
