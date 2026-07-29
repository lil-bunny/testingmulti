import pytest
import types
import uuid
import tempfile
import boto3
from unittest.mock import AsyncMock, patch

from PIL import Image

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.pod_lifecycle.ingress_service import (
    POD_EMAIL_SKIP_INVALID_ATTACHMENT,
    ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
    ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
    RouteCompletedDuplicateResult,
    RouteCompletedIngressGateResult,
)
from app.services.pod_lifecycle.attachment_pipeline_service import (
    PodAttachmentPipelineResult,
)
from app.services.workflow_lifecycle_service import LifecycleResolution
from app.services.workflow_service import WorkflowService
from app.workflows.compiler.compiler import compile_graph
from app.workflows.validators import validate_graph_definition
from app.services.s3bucket_service import S3Bucket, bucket, normalize_object_key
from app.workflows.nodes import turvo as turvo_nodes
from app.workflows import registry as workflow_registry
from botocore.stub import Stubber
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def _eligible_pod_attachment_pipeline_result() -> PodAttachmentPipelineResult:
    stage_dir = tempfile.mkdtemp(prefix="pod_email_test_")
    source_path = f"{stage_dir}/sources/001_att1.pdf"
    import os

    os.makedirs(f"{stage_dir}/sources", exist_ok=True)
    with open(source_path, "wb") as fh:
        fh.write(b"%PDF-1.4 mock pod file")
    return PodAttachmentPipelineResult(
        success=True,
        stage_dir=stage_dir,
        state_patch={
            "attachment_normalization": {
                "success": True,
                "assess_only": True,
                "source_attachment_ids": ["att-1"],
                "pod_merged_pdf_object_key": None,
                "pod_merge_source_paths": [source_path],
                "pod_vision_image_paths": [],
            },
            "pod_merge_source_paths": [source_path],
            "pod_vision_image_paths": [],
            "pod_source_object_keys": ["pod_attachments/pod_att1_SHIP.bin"],
            "has_attachments": True,
            "pod_attachment_stage_dir": stage_dir,
        },
    )


def _mock_t3ra_tenant(monkeypatch, *, use_db_tenant: bool = True) -> dict:
    """Patch tenant lookup; optional real DB row id for lifecycle FK tests."""
    if use_db_tenant:
        from app.services.tenants_service import TenantsService

        real_row = TenantsService().get_by_slug("t3ra")
        if real_row is None:
            pytest.skip("t3ra tenant not in test DB")
        row = {**real_row, "settings": minimal_t3ra_tenant_settings()}
    else:
        row = {
            "id": "aaaaaaaa-bbbb-cccc-dddd-000000000001",
            "slug": "t3ra",
            "settings": minimal_t3ra_tenant_settings(),
        }

    monkeypatch.setattr(
        "app.services.tenants_service.TenantsService.get_by_slug",
        lambda self, slug: row if slug == "t3ra" else None,
    )
    return row


@pytest.fixture
def mock_attachment_upload(monkeypatch):
    # Keep workflow tests isolated from real Unipile and S3 calls.
    def fake_upload_file(**kwargs):
        # Match ``S3Bucket.upload_file`` contract: all four keys, every time.
        return {
            "success": True,
            "object_key": "pod_attachments/pod_attId.pdf",
            "error_message": None,
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.bucket.upload_file",
        fake_upload_file,
    )


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_runs_to_completion(monkeypatch):
    _mock_t3ra_tenant(monkeypatch)
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
    # check_route_completed_pod_gate calls this directly (not via turvo_nodes.check_pod_tool
    # above), and does its own real Turvo tms-credentials lookup from the DB.
    monkeypatch.setattr(
        "app.services.pod_lifecycle.ingress_service.check_pod_by_shipment_id",
        AsyncMock(return_value={"success": True, "pod_exists": False}),
    )

    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "route_completed",
            "shipment_id": sid,
            "load_id": load_id,
            "to": "ana.gelita.test@freightx.ai",
        },
    )

    assert result["tenant_slug"] == "t3ra"
    assert result["data"]["shipment"]["shipment_id"] == sid
    uuid.UUID(result["data"]["workflow_lifecycle_id"])


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_duplicate_returns_early(monkeypatch):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    lifecycle_id = "11111111-2222-3333-4444-555555555555"

    with patch(
        "app.services.workflow_service.PodLifecycleIngressService"
    ) as ingress_cls:
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(
                is_duplicate=True,
                lifecycle_id=lifecycle_id,
            )
        )
        ingress_cls.return_value.enrich_payload_load_id.side_effect = (
            lambda **kwargs: kwargs["payload"]
        )
        service = WorkflowService(WorkflowRepository(), TenantRepository())

        execute_called = False

        async def fake_execute(*args, **kwargs):
            nonlocal execute_called
            execute_called = True
            return {}

        monkeypatch.setattr(service.execution, "execute", fake_execute)

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "route_completed",
                "shipment_id": "1000304706",
                "load_id": "56368",
                "to": "ana.gelita.test@freightx.ai",
            },
        )

    assert execute_called is False
    assert result["data"]["skipped_duplicate_route_completed"] is True
    assert result["data"]["workflow_lifecycle_id"] == lifecycle_id


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_convoy_skip_returns_early(monkeypatch):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    with patch(
        "app.services.workflow_service.PodLifecycleIngressService"
    ) as ingress_cls:
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(is_duplicate=False)
        )
        ingress_cls.return_value.check_route_completed_convoy_gate = AsyncMock(
            return_value=RouteCompletedIngressGateResult(
                skip=True,
                reason=ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
            )
        )
        ingress_cls.return_value.check_route_completed_pod_gate = AsyncMock(
            return_value=RouteCompletedIngressGateResult(skip=False)
        )
        ingress_cls.return_value.enrich_payload_load_id.side_effect = (
            lambda **kwargs: kwargs["payload"]
        )
        service = WorkflowService(WorkflowRepository(), TenantRepository())

        execute_called = False

        async def fake_execute(*args, **kwargs):
            nonlocal execute_called
            execute_called = True
            return {}

        monkeypatch.setattr(service.execution, "execute", fake_execute)

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "route_completed",
                "shipment_id": "1000304706",
                "load_id": "56368",
            },
        )

    assert execute_called is False
    assert result["data"]["skipped_convoy_load"] is True
    assert result["data"]["route_completed_skip_reason"] == ROUTE_COMPLETED_SKIP_CONVOY_LOAD


@pytest.mark.asyncio
async def test_pod_lifecycle_route_completed_pod_exists_skip_returns_early(monkeypatch):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    with patch(
        "app.services.workflow_service.PodLifecycleIngressService"
    ) as ingress_cls:
        ingress_cls.return_value.check_route_completed_duplicate.return_value = (
            RouteCompletedDuplicateResult(is_duplicate=False)
        )
        ingress_cls.return_value.check_route_completed_convoy_gate = AsyncMock(
            return_value=RouteCompletedIngressGateResult(skip=False)
        )
        ingress_cls.return_value.check_route_completed_pod_gate = AsyncMock(
            return_value=RouteCompletedIngressGateResult(
                skip=True,
                reason=ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
            )
        )
        ingress_cls.return_value.enrich_payload_load_id.side_effect = (
            lambda **kwargs: kwargs["payload"]
        )
        service = WorkflowService(WorkflowRepository(), TenantRepository())

        execute_called = False

        async def fake_execute(*args, **kwargs):
            nonlocal execute_called
            execute_called = True
            return {}

        monkeypatch.setattr(service.execution, "execute", fake_execute)

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "route_completed",
                "shipment_id": "1000304706",
                "load_id": "56368",
            },
        )

    assert execute_called is False
    assert result["data"]["skipped_pod_already_exists"] is True
    assert result["data"]["route_completed_skip_reason"] == ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_routes_to_processing(
    mock_attachment_upload, monkeypatch
):
    _mock_t3ra_tenant(monkeypatch)
    ship = f"S2-{uuid.uuid4().hex[:10]}"
    def _fake_pymupdf_convert(pdf_path, temp_dir, **kwargs):
        path = f"{temp_dir}/page_001.jpg"
        Image.new("RGB", (8, 8), color="white").save(path, "JPEG")
        return [path]

    monkeypatch.setattr(
        "app.tools.pdf_to_images._convert_pdf_with_pymupdf_page_at_a_time",
        _fake_pymupdf_convert,
    )
    monkeypatch.setattr(
        "app.tools.pdf_to_images._convert_one_page",
        lambda *args, **kwargs: Image.new("RGB", (8, 8), color="white"),
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

    def fake_read_workflow_lifecycle(state):
        state.data["workflow_lifecycle_payload"] = {
            "found": True,
            "shipment_id": ship,
        }
        return state

    monkeypatch.setitem(
        workflow_registry.NODE_REGISTRY,
        "read_workflow_lifecycle",
        fake_read_workflow_lifecycle,
    )

    def fake_merge_local(state):
        stage = str(state.data.get("pod_attachment_stage_dir") or "").strip()
        merged = f"{stage}/pod_SHIP.pdf" if stage else "/tmp/pod_SHIP.pdf"
        if stage:
            with open(merged, "wb") as fh:
                fh.write(b"%PDF-1.4 merged")
        state.data["pod_merged_local_path"] = merged
        return state

    monkeypatch.setitem(
        workflow_registry.NODE_REGISTRY,
        "merge_pod_attachments_local",
        fake_merge_local,
    )

    def fake_trim(state):
        state.data["pod_trim_outcome"] = "continue"
        return state

    monkeypatch.setitem(
        workflow_registry.NODE_REGISTRY,
        "trim_ratecon_pages_from_pod",
        fake_trim,
    )

    def fake_upload_trimmed(state):
        state.data["pod_merged_pdf_object_key"] = "pod_attachments/pod_SHIP.pdf"
        state.data["pod_object_keys"] = ["pod_attachments/pod_SHIP.pdf"]
        state.data["documents_pod"] = {"stored": True, "id": "doc-pipeline-1"}
        return state

    monkeypatch.setitem(
        workflow_registry.NODE_REGISTRY,
        "upload_trimmed_pod_attachments",
        fake_upload_trimmed,
    )

    def fake_pod_analysis(state):
        state.data["pod_analysis_results"] = {
            "success": True,
            "skipped": False,
            "findings": {
                "pages": [{"page_number": 1, "page_type": "BILL_OF_LADING"}],
                "pod_observations": {"delivery_signature_present": True},
            },
        }
        state.data["pod_analysis_stored"] = True
        state.data["pod_analysis_id"] = "da-1"
        return state

    monkeypatch.setitem(
        workflow_registry.NODE_REGISTRY,
        "pod_analysis",
        fake_pod_analysis,
    )

    with patch(
        "app.services.workflow_service.PodLifecycleIngressService.prepare_email_received_payload",
        new=AsyncMock(side_effect=lambda **kwargs: dict(kwargs["payload"])),
    ):
        service = WorkflowService(WorkflowRepository(), TenantRepository())
        service._pod_attachment_pipeline.run_for_email_payload = AsyncMock(
            return_value=_eligible_pod_attachment_pipeline_result()
        )

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "email_received",
                "thread_id": "thread-1",
                "body": "Attached POD for delivered load",
                "attachments": [{"id": "att-1"}],
                "has_attachments": True,
                "workflow_lifecycle_payload": {"found": True, "shipment_id": ship},
                "shipment_id": ship,
            },
        )

    assert result["data"]["shipment"]["shipment_id"] == ship
    assert result["data"].get("pod_object_keys")


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_uses_ingress_and_routes_to_processing(
    mock_attachment_upload, monkeypatch
):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    """Ingress enriches correlation keys; graph runs without mocking read_workflow_lifecycle."""
    ship = f"S2-{uuid.uuid4().hex[:10]}"
    shipments_row_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    lifecycle_id = "11111111-2222-3333-4444-555555555555"

    async def fake_prepare_email_received_payload(**kwargs):
        base = dict(kwargs["payload"])
        base["shipments_row_id"] = shipments_row_id
        base["shipment_id"] = ship
        base["workflow_lifecycle_id"] = lifecycle_id
        return base

    def _fake_pymupdf_convert(pdf_path, temp_dir, **kwargs):
        path = f"{temp_dir}/page_001.jpg"
        Image.new("RGB", (8, 8), color="white").save(path, "JPEG")
        return [path]

    monkeypatch.setattr(
        "app.tools.pdf_to_images._convert_pdf_with_pymupdf_page_at_a_time",
        _fake_pymupdf_convert,
    )
    monkeypatch.setattr(
        "app.tools.pdf_to_images._convert_one_page",
        lambda *args, **kwargs: Image.new("RGB", (8, 8), color="white"),
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

    def fake_read_lifecycle(self, **kwargs):
        return {
            "found": True,
            "lifecycle_id": lifecycle_id,
            "shipment_id": shipments_row_id,
            "workflow_name": "pod_lifecycle",
        }

    monkeypatch.setattr(
        "app.services.workflow_lifecycle_service.WorkflowLifecycleService.read_lifecycle",
        fake_read_lifecycle,
    )

    with patch(
        "app.services.workflow_service.PodLifecycleIngressService.prepare_email_received_payload",
        new=AsyncMock(side_effect=fake_prepare_email_received_payload),
    ) as mock_prepare:
        service = WorkflowService(WorkflowRepository(), TenantRepository())
        service._pod_attachment_pipeline.run_for_email_payload = AsyncMock(
            return_value=_eligible_pod_attachment_pipeline_result()
        )

        async def fake_execute(**kwargs):
            payload = kwargs.get("payload") or {}
            return {
                "tenant_id": kwargs.get("tenant_id"),
                "tenant_slug": kwargs.get("tenant_slug"),
                "execution_id": payload.get("execution_id"),
                "data": {
                    **payload,
                    "workflow_lifecycle_id": lifecycle_id,
                    "shipments_row_id": shipments_row_id,
                    "shipment": {"shipment_id": ship},
                    "pod_object_keys": ["pod_attachments/pod_attId.pdf"],
                },
            }

        monkeypatch.setattr(service.execution, "execute", fake_execute)
        monkeypatch.setattr(
            service.lifecycle_service,
            "resolve_or_create_lifecycle",
            lambda **kw: LifecycleResolution(
                workflow_lifecycle_id=lifecycle_id,
                existed=True,
            ),
        )

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "email_received",
                "thread_id": "thread-1",
                "body": "Attached POD for delivered load",
                "attachments": [{"id": "att-1"}],
                "has_attachments": True,
            },
        )

    mock_prepare.assert_called_once()
    assert result["data"]["workflow_lifecycle_id"] == lifecycle_id
    assert result["data"]["shipments_row_id"] == shipments_row_id
    assert result["data"]["shipment"]["shipment_id"] == ship
    assert result["data"].get("pod_object_keys")


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_skips_invalid_attachment_at_pipeline(
    monkeypatch,
):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    ship = f"S-gate-{uuid.uuid4().hex[:8]}"

    async def fake_prepare(**kwargs):
        base = dict(kwargs["payload"])
        base["shipment_id"] = ship
        base["email_id"] = "email-gate-1"
        base["account_id"] = "acct-1"
        return base

    execute_called = False

    async def fake_execute(**kwargs):
        nonlocal execute_called
        execute_called = True
        return {}

    with patch(
        "app.services.workflow_service.PodLifecycleIngressService.prepare_email_received_payload",
        new=AsyncMock(side_effect=fake_prepare),
    ):
        service = WorkflowService(WorkflowRepository(), TenantRepository())
        service._pod_attachment_pipeline.run_for_email_payload = AsyncMock(
            return_value=PodAttachmentPipelineResult(
                success=False,
                skip_reason=POD_EMAIL_SKIP_INVALID_ATTACHMENT,
                state_patch={
                    "attachment_normalization": {
                        "success": False,
                        "error": "No valid document",
                    }
                },
            )
        )
        monkeypatch.setattr(service.execution, "execute", fake_execute)
        monkeypatch.setattr(
            service.lifecycle_service,
            "resolve_or_create_lifecycle",
            lambda **kw: LifecycleResolution(
                workflow_lifecycle_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                existed=False,
            ),
        )

        result = await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "email_received",
                "thread_id": "thread-gate",
                "attachments": [{"id": "att-bad"}],
                "has_attachments": True,
            },
        )

    assert execute_called is False
    assert result["data"]["skipped_pod_email_ingress"] is True
    assert result["data"]["pod_email_ingress_skip_reason"] == POD_EMAIL_SKIP_INVALID_ATTACHMENT
    assert result["data"]["workflow_lifecycle_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_pod_lifecycle_email_received_carries_pipeline_artifact_state(
    monkeypatch,
):
    _mock_t3ra_tenant(monkeypatch, use_db_tenant=False)
    ship = f"S-norm-{uuid.uuid4().hex[:8]}"
    lifecycle_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    pipeline_result = _eligible_pod_attachment_pipeline_result()

    async def fake_prepare(**kwargs):
        base = dict(kwargs["payload"])
        base["shipment_id"] = ship
        base["workflow_lifecycle_id"] = lifecycle_id
        return base

    captured_payload: dict = {}

    async def fake_execute(**kwargs):
        captured_payload.update(kwargs.get("payload") or {})
        return {
            "tenant_id": kwargs.get("tenant_id"),
            "tenant_slug": kwargs.get("tenant_slug"),
            "execution_id": (kwargs.get("payload") or {}).get("execution_id"),
            "data": dict(kwargs.get("payload") or {}),
        }

    with patch(
        "app.services.workflow_service.PodLifecycleIngressService.prepare_email_received_payload",
        new=AsyncMock(side_effect=fake_prepare),
    ):
        service = WorkflowService(WorkflowRepository(), TenantRepository())
        service._pod_attachment_pipeline.run_for_email_payload = AsyncMock(
            return_value=pipeline_result
        )
        monkeypatch.setattr(service.execution, "execute", fake_execute)
        monkeypatch.setattr(
            service.lifecycle_service,
            "resolve_or_create_lifecycle",
            lambda **kw: LifecycleResolution(
                workflow_lifecycle_id=lifecycle_id,
                existed=True,
            ),
        )

        await service.run(
            tenant_slug="t3ra",
            workflow_name="pod_lifecycle",
            payload={
                "event_type": "email_received",
                "thread_id": "thread-norm",
                "attachments": [{"id": "att-1"}],
            },
        )

    pipeline_call = service._pod_attachment_pipeline.run_for_email_payload.await_args
    assert (
        pipeline_call.kwargs["payload"]["workflow_lifecycle_id"] == lifecycle_id
    )
    assert captured_payload.get("pod_merge_source_paths")
    assert captured_payload.get("has_attachments") is True
    assert captured_payload.get("pod_attachment_stage_dir") == pipeline_result.stage_dir
    assert "pod_merged_pdf_object_key" not in captured_payload
    assert "documents_pod" not in captured_payload
    assert "pod_attachment_stage_files" not in captured_payload


@pytest.mark.asyncio
async def test_pod_lifecycle_reminder_due_missing_attachment_routes_to_email(monkeypatch):
    _mock_t3ra_tenant(monkeypatch)
    service = WorkflowService(WorkflowRepository(), TenantRepository())

    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="pod_lifecycle",
        payload={
            "event_type": "reminder_due",
            "shipment_id": "S3",
            "to": "ana.gelita.test@freightx.ai",
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
            "Key": "pod_attachments/pod_attId.pdf",
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
    assert result["object_key"] == "pod_attachments/pod_attId.pdf"
    assert result["error_message"] is None
    stubber.assert_no_pending_responses()


def test_normalize_object_key_strips_and_rejects_urls():
    assert normalize_object_key("  pod_attachments/a.pdf ") == (
        "pod_attachments/a.pdf"
    )
    assert normalize_object_key("/pod_attachments/a.pdf") == (
        "pod_attachments/a.pdf"
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
        {"Bucket": "test-bucket", "Key": "pod_attachments/x.pdf"},
    )
    bucket = S3Bucket(s3_client=fake_s3_client, bucket_name="test-bucket")
    with stubber:
        result = bucket.delete_file("pod_attachments/x.pdf")
    assert result["success"] is True
    assert result["object_key"] == "pod_attachments/x.pdf"
    stubber.assert_no_pending_responses()
