import pytest
import types
import uuid
import boto3

from PIL import Image

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services import pod_extraction as pod_extraction_service
from app.services.workflow_service import WorkflowService
from app.workflows.compiler.compiler import compile_graph
from app.workflows.validators import validate_graph_definition
from app.services.s3bucket_service import S3Bucket, bucket, normalize_object_key
from app.workflows.nodes import email as email_nodes
from app.workflows.nodes import turvo as turvo_nodes
from botocore.stub import Stubber


@pytest.fixture
def mock_attachment_upload(monkeypatch):
    # Keep workflow tests isolated from real Unipile and S3 calls.
    def fake_get_attachment(email_id, attachment_id, account_id):
        return b"%PDF-1.4 mock pod file"

    def fake_upload_file(**kwargs):
        # Match ``S3Bucket.upload_file`` contract: all four keys, every time.
        return {
            "success": True,
            "object_key": "freightx/pod_attachments/pod_attId.pdf",
            "error_message": None,
        }

    monkeypatch.setattr(email_nodes, "get_email_attachments_tool", fake_get_attachment)
    monkeypatch.setattr(email_nodes.bucket, "upload_file", fake_upload_file)


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_runs_to_completion(monkeypatch):
    sid = f"S1-{uuid.uuid4().hex[:10]}"
    load_id = f"L1-{uuid.uuid4().hex[:8]}"

    def fake_get_shipment(sid_arg, *, tenant_slug=None):
        return {
            "shipment_id": sid_arg or sid,
            "convoy": False,
            "details": {"carrierOrder": [{"carrier": {"name": "Acme Transport"}}]},
        }

    monkeypatch.setattr(turvo_nodes, "get_shipment_tool", fake_get_shipment)
    monkeypatch.setattr(
        turvo_nodes,
        "check_pod_tool",
        lambda *a, **k: {"success": True, "pod_exists": False},
    )

    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "route_completed",
            "shipment_id": sid,
            "load_id": load_id,
            "to": "ops@example.com",
        },
    )

    assert result["tenant_slug"] == "t3ra"
    assert result["data"]["shipment"]["shipment_id"] == sid
    uuid.UUID(result["data"]["workflow_lifecycle_id"])


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_routes_to_processing(
    mock_attachment_upload, monkeypatch
):
    ship = f"S2-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        pod_extraction_service,
        "convert_from_path",
        lambda *args, **kwargs: [Image.new("RGB", (8, 8), color="white")],
    )

    def fake_get_shipment(sid, *, tenant_slug=None):
        return {
            "shipment_id": sid or ship,
            "convoy": False,
            "data": {"status": {"code": {"key": "2116"}}},
            "details": {
                "status": {"code": {"key": "2116"}},
                "carrierOrder": [{"carrier": {"name": "Acme Transport"}}],
            },
        }

    monkeypatch.setattr(turvo_nodes, "get_shipment_tool", fake_get_shipment)
    monkeypatch.setattr(
        turvo_nodes,
        "check_pod_tool",
        lambda *a, **k: {"success": True, "pod_exists": False},
    )

    def fake_download_object_bytes(self, object_key):
        return {
            "success": True,
            "body": b"%PDF-1.4 mock",
            "object_key": object_key,
            "error_message": None,
        }

    monkeypatch.setattr(
        bucket,
        "download_object_bytes",
        types.MethodType(fake_download_object_bytes, bucket),
    )

    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-1",
            "body": "Attached POD for delivered load",
            "attachments": [{"id": "att-1"}],
            "has_attachments": True,
            "workflow_lifecycle_payload": {"shipment_id": ship},
            "shipment_id": ship,
        },
    )

    assert result["data"]["shipment"]["shipment_id"] == ship
    assert result["data"].get("pod_object_keys")


@pytest.mark.asyncio
async def test_pod_lifecycle_reminder_due_missing_attachment_routes_to_email():
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_slug="t3ra",
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
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={"shipment_id": "S1"},
        )


@pytest.mark.asyncio
async def test_thread_id_reuses_existing_workflow_lifecycle_id(mock_attachment_upload):
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    first = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-42",
            "shipment_id": "S42",
            "attachments": [{"id": "a1"}],
            "workflow_lifecycle_payload": {"shipment_id": "S42"},
        },
    )
    workflow_lifecycle_id = first["data"]["workflow_lifecycle_id"]

    second = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-42",
            "attachments": [{"id": "a2"}],
            "workflow_lifecycle_payload": {"shipment_id": "S42"},
            "shipment_id": "S42",
        },
    )

    assert second["data"]["workflow_lifecycle_id"] == workflow_lifecycle_id


def test_upload_file_puts_object_to_s3():
    fake_s3_client = boto3.client(
        "s3",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    stubber = Stubber(fake_s3_client)
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": "test-bucket",
            "Key": "freightx/pod_attachments/pod_attId.pdf",
            "Body": b"%PDF-1.4 mock pod file",
            "ContentType": "application/pdf",
        },
    )
    bucket = S3Bucket(
        s3_client=fake_s3_client,
        bucket_name="test-bucket",
    )
    with stubber:
        result = bucket.upload_file(
            file_content=b"%PDF-1.4 mock pod file",
            filename="pod_attId.pdf",
            folder="pod_attachments",
            content_type="application/pdf",
        )
    assert result["success"] is True
    assert result["object_key"] == "freightx/pod_attachments/pod_attId.pdf"
    assert result["error_message"] is None
    stubber.assert_no_pending_responses()


def test_normalize_object_key_strips_and_rejects_urls():
    assert normalize_object_key("  freightx/pod_attachments/a.pdf ") == (
        "freightx/pod_attachments/a.pdf"
    )
    assert normalize_object_key("/freightx/pod_attachments/a.pdf") == (
        "freightx/pod_attachments/a.pdf"
    )
    with pytest.raises(ValueError, match="object key"):
        normalize_object_key("https://example.com/o.pdf")


def test_delete_file_accepts_bare_object_key():
    fake_s3_client = boto3.client(
        "s3",
        region_name="us-west-2",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    stubber = Stubber(fake_s3_client)
    stubber.add_response(
        "delete_object",
        {},
        {"Bucket": "test-bucket", "Key": "freightx/pod_attachments/x.pdf"},
    )
    bucket = S3Bucket(s3_client=fake_s3_client, bucket_name="test-bucket")
    with stubber:
        result = bucket.delete_file("freightx/pod_attachments/x.pdf")
    assert result["success"] is True
    assert result["object_key"] == "freightx/pod_attachments/x.pdf"
    stubber.assert_no_pending_responses()
