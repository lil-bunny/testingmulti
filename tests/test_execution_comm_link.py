"""ExecutionService links inbound communications to workflow runs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.execution_service import ExecutionService

_COMM_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_execute_links_communication_to_workflow_run() -> None:
    graph = MagicMock()
    graph.invoke.return_value = {"data": {}}

    with (
        patch.object(ExecutionService, "__init__", lambda self: None),
        patch(
            "app.services.execution_service.WorkflowRunsService"
        ) as runs_cls,
        patch(
            "app.services.execution_service.CommunicationsService"
        ) as comm_cls,
    ):
        svc = ExecutionService()
        svc.runs_service = runs_cls.return_value
        svc._communications = comm_cls.return_value

        payload = {
            "event_type": "email_received",
            "communication_id": _COMM_UUID,
        }
        await svc.execute(
            graph=graph,
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            payload=payload,
            execution_id=_RUN_UUID,
        )

    svc.runs_service.record_workflow_run.assert_called_once()
    svc._communications.link_inbound_to_workflow_run.assert_called_once_with(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
    )


@pytest.mark.asyncio
async def test_execute_skips_comm_link_without_communication_id() -> None:
    graph = MagicMock()
    graph.invoke.return_value = {"data": {}}

    with (
        patch.object(ExecutionService, "__init__", lambda self: None),
        patch("app.services.execution_service.WorkflowRunsService") as runs_cls,
        patch("app.services.execution_service.CommunicationsService") as comm_cls,
    ):
        svc = ExecutionService()
        svc.runs_service = runs_cls.return_value
        svc._communications = comm_cls.return_value

        await svc.execute(
            graph=graph,
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            payload={"event_type": "route_completed"},
            execution_id=_RUN_UUID,
        )

    svc._communications.link_inbound_to_workflow_run.assert_not_called()


@pytest.mark.asyncio
async def test_execute_carrier_email_received_links_lifecycle() -> None:
    graph = MagicMock()
    graph.invoke.return_value = {"data": {}}

    with (
        patch.object(ExecutionService, "__init__", lambda self: None),
        patch("app.services.execution_service.WorkflowRunsService") as runs_cls,
        patch("app.services.execution_service.CommunicationsService") as comm_cls,
    ):
        svc = ExecutionService()
        svc.runs_service = runs_cls.return_value
        svc._communications = comm_cls.return_value

        payload = {
            "event_type": "carrier_email_received",
            "communication_id": _COMM_UUID,
            "routing_guide_attempt": 2,
            "thread_id": "thread-carrier-2",
        }
        await svc.execute(
            graph=graph,
            tenant_id=_TENANT_UUID,
            tenant_slug="gelita",
            workflow_lifecycle_id=_LIFECYCLE_UUID,
            payload=payload,
            execution_id=_RUN_UUID,
        )

    svc._communications.link_carrier_email_received_communication.assert_called_once_with(
        communication_id=_COMM_UUID,
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        routing_guide_attempt=2,
    )
    svc._communications.link_workflow_run_to_thread.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        thread_id="thread-carrier-2",
        workflow_run_id=_RUN_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
    )
    svc._communications.link_inbound_to_workflow_run.assert_not_called()
