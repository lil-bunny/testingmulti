"""Tests for tender carrier assignment on ``carrier_email_received``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.services.routing_guide_lookup_service import RoutingGuideCarrierResolution
from app.services.tender_service import TenderService
from tests.fixtures.tenant_settings import load_tenant_settings_dev

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _tenant_settings() -> dict:
    return load_tenant_settings_dev("gelita")


def _ftl_state(*, attempt: int = 1) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tenant_settings": _tenant_settings(),
            "routing_guide_attempt": attempt,
            "workflow_lifecycle_metadata": {"routing_guide_attempt": attempt},
            "tender": {
                "load_type": "FTL",
                "order_number": "ORD-1",
                "delivery_address": {"postal_code": "60601"},
            },
        },
    )


@patch("app.tools.routing_guide_carrier.resolve_carrier_for_tender")
def test_assign_carrier_from_routing_guide_persists_carrier_name(
    mock_resolve: MagicMock,
) -> None:
    mock_resolve.return_value = RoutingGuideCarrierResolution(
        lane=None,
        plan_carrier_name="Schneider",
        carrier_email="carrier@example.com",
        lane_miss=False,
        missing_carrier_email=False,
    )
    mock_tenders_repo = MagicMock()
    mock_tenders_repo.update_carrier_name.return_value = True

    service = TenderService(tenders_repository=mock_tenders_repo)
    state = _ftl_state(attempt=1)

    assert service.assign_carrier_from_routing_guide(state) is True
    mock_tenders_repo.update_carrier_name.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        carrier_name="Schneider",
    )


@patch("app.tools.routing_guide_carrier.resolve_carrier_for_tender")
def test_assign_carrier_from_routing_guide_lane_miss_sets_null(
    mock_resolve: MagicMock,
) -> None:
    mock_resolve.return_value = RoutingGuideCarrierResolution(
        lane=None,
        plan_carrier_name="",
        carrier_email="",
        lane_miss=True,
        missing_carrier_email=False,
    )
    mock_tenders_repo = MagicMock()
    mock_tenders_repo.update_carrier_name.return_value = True

    service = TenderService(tenders_repository=mock_tenders_repo)
    state = _ftl_state(attempt=2)

    assert service.assign_carrier_from_routing_guide(state) is True
    mock_tenders_repo.update_carrier_name.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        carrier_name=None,
    )
    mock_resolve.assert_called_once()
    assert mock_resolve.call_args.kwargs["attempt"] == 2


@patch("app.tools.routing_guide_carrier.resolve_carrier_for_tender")
def test_assign_carrier_from_routing_guide_skips_ltl(mock_resolve: MagicMock) -> None:
    mock_tenders_repo = MagicMock()
    service = TenderService(tenders_repository=mock_tenders_repo)
    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tenant_settings": _tenant_settings(),
            "tender": {"load_type": "LTL"},
        },
    )

    assert service.assign_carrier_from_routing_guide(state) is False
    mock_resolve.assert_not_called()
    mock_tenders_repo.update_carrier_name.assert_not_called()


@patch("app.workflows.nodes.record_tender_sent_to_carrier.TenderService")
@patch("app.workflows.nodes.record_tender_sent_to_carrier.LifecycleTransitionService")
def test_record_tender_sent_to_carrier_assigns_carrier_for_ftl(
    mock_lifecycle_cls: MagicMock,
    mock_tender_cls: MagicMock,
) -> None:
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_tender_sent_to_carrier import record_tender_sent_to_carrier

    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_tender = MagicMock()
    mock_tender_cls.return_value = mock_tender

    state = _ftl_state(attempt=1)
    record_tender_sent_to_carrier(state)

    mock_lifecycle.apply_from_state.assert_called_once()
    call_kwargs = mock_lifecycle.apply_from_state.call_args.kwargs
    assert call_kwargs["to_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER_1
    mock_tender.assign_carrier_from_routing_guide.assert_called_once_with(state)


@patch("app.workflows.nodes.record_tender_sent_to_carrier.TenderService")
@patch("app.workflows.nodes.record_tender_sent_to_carrier.LifecycleTransitionService")
def test_record_tender_sent_to_carrier_skips_carrier_assignment_for_ltl(
    mock_lifecycle_cls: MagicMock,
    mock_tender_cls: MagicMock,
) -> None:
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_tender_sent_to_carrier import record_tender_sent_to_carrier

    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_tender_cls.return_value = MagicMock()

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tenant_settings": _tenant_settings(),
            "tender": {"load_type": "LTL"},
        },
    )
    record_tender_sent_to_carrier(state)

    call_kwargs = mock_lifecycle.apply_from_state.call_args.kwargs
    assert call_kwargs["to_sub_status"] == StatusSubType.TENDER_SENT_TO_CARRIER
    mock_tender_cls.assert_not_called()
