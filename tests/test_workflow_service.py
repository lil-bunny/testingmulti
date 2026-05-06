import pytest
import types
import uuid
import boto3

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import WorkflowService
from app.tools import workflow_correlation as wc_module
from app.workflows.compiler.compiler import compile_graph
from app.workflows.validators import validate_graph_definition
from app.services.s3bucket_service import S3Bucket, bucket, normalize_object_key
from app.workflows.nodes import email as email_nodes
from app.workflows.nodes import turvo as turvo_nodes
from app.workflows.nodes import ratecon as ratecon_node
from app.models.document import DocumentType
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
async def test_pod_lifecycle_email_received_routes_to_processing(
    mock_attachment_upload, monkeypatch
):
    def fake_get_shipment(sid, app_user_id=None):
        return {
            "shipment_id": sid or "S2",
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
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "email_received",
            "thread_id": "thread-1",
            "body": "Attached POD for delivered load",
            "attachments": [{"id": "att-1"}],
            "has_attachments": True,
            "workflow_correlation_payload": {"shipment_id": "S2"},
            "shipment_id": "S2",
        },
    )

    assert result["data"]["is_pod_attached"] is True
    assert result["data"]["workflow_correlation"]["payload"]["shipment_id"] == "S2"
    assert result["data"]["workflow_correlation"]["found"] is True
    assert result["data"]["shipment"]["data"]["status"]["code"]["key"] in {"2116", "2106", "2105"}
    assert result["data"].get("pod_object_keys")


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
async def test_ratecon_requires_load_id():
    service = WorkflowService(WorkflowRepository(), TenantRepository())
    with pytest.raises(Exception, match="load_id"):
        await service.run(
            tenant_id="t3ra",
            workflow_name="ratecon",
            payload={"event_type": "route_completed"},
        )


@pytest.mark.asyncio
async def test_ratecon_runs_resolve_load_to_shipment(monkeypatch):
    def fake_load_id_to_shipment(load_id, app_user_id=None):
        return {
            "success": True,
            "load_id": str(load_id),
            "shipment_id": "SHIP-99",
            "message": "ok",
        }

    monkeypatch.setattr(
        turvo_nodes, "load_id_to_shipment_id_tool", fake_load_id_to_shipment
    )
    monkeypatch.setattr(
        wc_module,
        "persist_correlation_thread_for_shipment",
        lambda sid, lid, tid, **kwargs: {
            "stored": True,
            "workflow_correlation": {"key": sid, "payload": {}},
        },
    )

    service = WorkflowService(WorkflowRepository(), TenantRepository())
    result = await service.run(
        tenant_id="t3ra",
        workflow_name="ratecon",
        payload={"load_id": "L42", "app_user_id": "user-1"},
    )

    assert result["data"]["shipment_id"] == "SHIP-99"
    assert result["data"]["load_id_to_shipment"]["shipment_id"] == "SHIP-99"
    assert result["data"]["load_id_to_shipment"]["success"] is True


@pytest.mark.asyncio
async def test_ratecon_upload_persists_documents_via_insert_document(monkeypatch):
    def fake_load_id_to_shipment(load_id, app_user_id=None):
        return {
            "success": True,
            "load_id": str(load_id),
            "shipment_id": "SHIP-99",
            "message": "ok",
        }

    monkeypatch.setattr(
        turvo_nodes, "load_id_to_shipment_id_tool", fake_load_id_to_shipment
    )
    monkeypatch.setattr(
        wc_module,
        "persist_correlation_thread_for_shipment",
        lambda sid, lid, tid, **kwargs: {
            "stored": True,
            "workflow_correlation": {"key": sid, "payload": {}},
        },
    )

    expect_key = "freightx/ratecon_attachments/ratecon_SHIP-99.pdf"

    def fake_upload_to_s3(**kwargs):
        return {
            "results": [
                {
                    "attachment_id": "att-1",
                    "success": True,
                    "object_key": expect_key,
                    "error_message": None,
                    "original_filename": "Carrier_rate_confirmation.pdf",
                    "content_type": "application/pdf",
                    "extension": "pdf",
                }
            ],
            "ratecon_object_keys": [expect_key],
            "all_succeeded": True,
        }

    persisted: list[tuple] = []

    def fake_insert(doc_type, shipment_id, object_key, **kwargs):
        persisted.append((doc_type, shipment_id, object_key, kwargs))
        return {"stored": True, "id": "doc-row-1"}

    monkeypatch.setattr(
        ratecon_node,
        "upload_ratecon_email_attachments_to_s3",
        fake_upload_to_s3,
    )
    monkeypatch.setattr(ratecon_node, "insert_document", fake_insert)

    service = WorkflowService(WorkflowRepository(), TenantRepository())
    result = await service.run(
        tenant_id="t3ra",
        workflow_name="ratecon",
        payload={
            "load_id": "L42",
            "app_user_id": "user-1",
            "email_id": "email-1",
            "attachments": [{"id": "att-1"}],
        },
    )

    assert persisted
    assert persisted[0][0] == DocumentType.RATECON
    assert persisted[0][1] == "SHIP-99"
    assert persisted[0][2] == expect_key
    r0 = result["data"]["ratecon_s3_upload"]["results"][0]
    assert r0["document_persist"]["stored"] is True
    assert r0["document_persist"]["id"] == "doc-row-1"


@pytest.mark.asyncio
async def test_thread_id_reuses_existing_workflow_instance_id(mock_attachment_upload):
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
