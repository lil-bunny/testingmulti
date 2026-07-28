"""Send-branch graph nodes: lifecycle transitions only after Turvo placeholder."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.appointment_scheduling.email_service import SendResult
from app.services.appointment_scheduling.turvo_stop_update_service import TurvoConfirmResult
from app.workflows.nodes.appointment_scheduling.nodes import (
    apply_turvo_delivery_placeholder,
    finalize_appointment_awaiting_reply,
    send_appointment_draft_email,
)


def _state(**overrides):
    data = {
        "workflow_lifecycle_id": "11111111-2222-3333-4444-555555555555",
        "tenant_id": "00000000-0000-4000-8000-0000000000e1",
        "tenant_slug": "t3ra",
        "shipment_id": "ship-1",
        "tenant_settings": {"mikey_account_id": "acc-1"},
        "email_draft": {
            "to": ["wh@example.com"],
            "subject": "DEL APPT REQ",
            "full_html": "<p>Hello</p>",
        },
    }
    data.update(overrides)
    return SimpleNamespace(
        tenant_id=data["tenant_id"],
        execution_id="run-1",
        data=data,
    )


@patch("app.workflows.nodes.appointment_scheduling.nodes.LifecycleService")
@patch("app.workflows.nodes.appointment_scheduling.nodes.TurvoStopUpdateService")
@patch("app.workflows.nodes.appointment_scheduling.nodes.EmailService")
def test_send_branch_awaiting_reply_transition_only_on_finalize(
    mock_email_cls: MagicMock,
    mock_turvo_cls: MagicMock,
    mock_lifecycle_cls: MagicMock,
) -> None:
    lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = lifecycle

    email = MagicMock()
    email.send_draft_from_state.return_value = SendResult(
        sent=True,
        communication_id="comm-1",
    )
    mock_email_cls.return_value = email

    turvo = MagicMock()
    turvo.apply_delivery_placeholder_from_state.return_value = TurvoConfirmResult(
        ok=True,
        updated=True,
    )
    mock_turvo_cls.return_value = turvo

    state = _state()

    send_appointment_draft_email(state)
    apply_turvo_delivery_placeholder(state)
    lifecycle.finalize_appointment_awaiting_reply.assert_not_called()

    finalize_appointment_awaiting_reply(state)
    lifecycle.finalize_appointment_awaiting_reply.assert_called_once_with(state)

    email.send_draft_from_state.assert_called_once()
    turvo.apply_delivery_placeholder_from_state.assert_called_once()
