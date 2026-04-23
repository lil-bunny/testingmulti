import pytest
import uuid

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import WorkflowService
from app.workflows.compiler.compiler import compile_graph
from app.workflows.validators import validate_graph_definition


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_runs_to_completion():
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "route_completed",
            "shipment_id": "S1",
            "load_id": "L1",
            "to": "ops@example.com",
        },
    )

    assert result["tenant_id"] == "t3ra"
    assert result["data"]["shipment"]["shipment_id"] == "S1"
    uuid.UUID(result["data"]["workflow_instance_id"])


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_routes_to_processing():
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-1",
            "body": "Attached POD for delivered load",
            "attachments": [{"id": "att-1"}],
            "workflow_correlation_payload": {"shipment_id": "S2"},
            "shipment_id": "S2",
        },
    )

    assert result["data"]["is_pod_reply_mail"] is True
    assert result["data"]["workflow_correlation"]["payload"]["shipment_id"] == "S2"
    assert result["data"]["pod_processing"]["success"] is True


@pytest.mark.asyncio
async def test_pod_lifecycle_reminder_due_missing_attachment_routes_to_email():
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "reminder_due",
            "shipment_id": "S3",
            "to": "ops@example.com",
        },
    )

    assert result["data"]["pod_exists"] is False


def test_tenant_compile_supports_replace_rules():
    base = {
        "entry": "a",
        "exit": "end",
        "nodes": ["a", "b", "end"],
        "edges": [["a", "b"], ["b", "end"]],
        "routers": {"a": {"router": "always", "map": {"go": "b"}}},
    }

    tenant_config = {"replace": {"b": "c"}}
    compiled = compile_graph(base, tenant_config)

    assert "c" in compiled["nodes"]
    assert ["a", "c"] in compiled["edges"]
    assert compiled["routers"]["a"]["map"]["go"] == "c"


def test_graph_definition_validation_rejects_unknown_edge_nodes():
    invalid = {
        "entry": "a",
        "exit": "end",
        "nodes": ["a", "end"],
        "edges": [["a", "missing"]],
        "routers": {},
    }
    with pytest.raises(ValueError):
        validate_graph_definition(invalid)


@pytest.mark.asyncio
async def test_required_payload_keys_enforced():
    service = WorkflowService(WorkflowRepository(), TenantRepository())
    with pytest.raises(Exception):
        await service.run(
            tenant_id="t3ra",
            workflow_name="pod_lifecycle",
            payload={"shipment_id": "S1"},
        )


@pytest.mark.asyncio
async def test_thread_id_reuses_existing_workflow_instance_id():
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    first = await service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-42",
            "shipment_id": "S42",
            "attachments": [{"id": "a1"}],
            "workflow_correlation_payload": {"shipment_id": "S42"},
        },
    )
    workflow_instance_id = first["data"]["workflow_instance_id"]

    second = await service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-42",
            "attachments": [{"id": "a2"}],
            "workflow_correlation_payload": {"shipment_id": "S42"},
            "shipment_id": "S42",
        },
    )

    assert second["data"]["workflow_instance_id"] == workflow_instance_id
