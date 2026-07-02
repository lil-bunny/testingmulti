"""Tests for pod_lifecycle reminder scheduling helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_T3RA_SETTINGS = minimal_t3ra_tenant_settings()


@patch("app.workflows.nodes.pod_request.WorkflowReminderService")
def test_record_and_schedule_hydrates_account_id_before_enqueue(
    mock_service_cls: MagicMock,
) -> None:
    from app.workflows.nodes.pod_request import record_and_schedule_pod_request

    captured: dict = {}

    def _schedule(data, *, workflow_name: str) -> None:
        captured["data"] = dict(data)
        captured["workflow_name"] = workflow_name
        data["reminders_scheduled"] = True

    mock_service_cls.return_value.schedule.side_effect = _schedule

    state = WorkflowState(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={
            "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "tenant_slug": "t3ra",
            "workflow_lifecycle_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "tenant_settings": _T3RA_SETTINGS,
            "event_type": "route_completed",
        },
    )

    record_and_schedule_pod_request(state)

    assert captured["workflow_name"] == "pod_lifecycle"
    assert captured["data"]["account_id"] == "test-mikey-account-id"
    assert state.data["reminders_scheduled"] is True
