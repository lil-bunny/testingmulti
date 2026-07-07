"""CommunicationsService carrier ingress link + lifecycle id."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.communications.service import CommunicationsService

_COMM_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@patch.object(CommunicationsService, "__init__", lambda self: None)
def test_link_carrier_email_received_communication_links_lifecycle() -> None:
    svc = CommunicationsService()
    svc.link_inbound_to_workflow_run = MagicMock(return_value=True)

    linked = svc.link_carrier_email_received_communication(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        routing_guide_attempt=1,
    )

    assert linked is True
    svc.link_inbound_to_workflow_run.assert_called_once_with(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
    )


@patch.object(CommunicationsService, "__init__", lambda self: None)
def test_link_carrier_email_received_without_lifecycle_id() -> None:
    svc = CommunicationsService()
    svc.link_inbound_to_workflow_run = MagicMock(return_value=True)

    svc.link_carrier_email_received_communication(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        routing_guide_attempt=2,
    )

    svc.link_inbound_to_workflow_run.assert_called_once_with(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=None,
    )
