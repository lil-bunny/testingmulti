"""CommunicationsService carrier ingress link + attempt metadata."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.communications.service import CommunicationsService

_COMM_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@patch.object(CommunicationsService, "__init__", lambda self: None)
def test_link_carrier_email_received_communication_links_and_stamps_attempt() -> None:
    svc = CommunicationsService()
    svc.link_inbound_to_workflow_run = MagicMock(return_value=True)
    svc.patch_communication_metadata = MagicMock(return_value=True)

    linked = svc.link_carrier_email_received_communication(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        routing_guide_attempt=1,
    )

    assert linked is True
    svc.link_inbound_to_workflow_run.assert_called_once_with(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
    )
    svc.patch_communication_metadata.assert_called_once_with(
        communication_id=_COMM_UUID,
        metadata_patch={"routing_guide_attempt": 1},
    )


@patch.object(CommunicationsService, "__init__", lambda self: None)
def test_link_carrier_email_received_still_patches_when_link_idempotent() -> None:
    svc = CommunicationsService()
    svc.link_inbound_to_workflow_run = MagicMock(return_value=False)
    svc.patch_communication_metadata = MagicMock(return_value=True)

    svc.link_carrier_email_received_communication(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        routing_guide_attempt=2,
    )

    svc.patch_communication_metadata.assert_called_once()


@patch.object(CommunicationsService, "__init__", lambda self: None)
def test_link_carrier_email_received_skips_patch_without_attempt() -> None:
    svc = CommunicationsService()
    svc.link_inbound_to_workflow_run = MagicMock(return_value=True)
    svc.patch_communication_metadata = MagicMock()

    svc.link_carrier_email_received_communication(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        routing_guide_attempt=None,
    )

    svc.patch_communication_metadata.assert_not_called()
