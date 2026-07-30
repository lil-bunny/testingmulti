"""t3ra ratecon workflow: ingress, graph run, and document upload (mocked)."""

from __future__ import annotations

import uuid

import pytest

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_lifecycle_service import (
    LifecycleResolution,
    WorkflowLifecycleService,
)
from app.services.workflow_service import WorkflowService
from app.services.ratecon_document_service import RateconDocumentService
from app.workflows.nodes import turvo as turvo_nodes

_RATECON_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def ratecon_lifecycle_stubs(monkeypatch):
    """Avoid DB lifecycle insert with mocked shipment row (FK requires real shipments)."""
    lifecycle_id = str(uuid.uuid4())

    def fake_resolve(self, *, tenant_id, workflow_name, payload):
        return LifecycleResolution(
            workflow_lifecycle_id=lifecycle_id,
            existed=False,
        )

    def fake_check(self, *, tenant_id, workflow_name, **kwargs):
        return {"exists": True, "lifecycle_id": lifecycle_id}

    monkeypatch.setattr(
        WorkflowLifecycleService,
        "resolve_or_create_lifecycle",
        fake_resolve,
    )
    monkeypatch.setattr(
        WorkflowLifecycleService,
        "check_lifecycle_exists",
        fake_check,
    )


@pytest.fixture
def ratecon_ingress_mocks(monkeypatch):
    """Pre-graph Turvo resolve + shipment upsert (RateconIngressService)."""

    async def fake_resolve(slug, load_id, **kwargs):
        return "SHIP-99"

    async def fake_get(slug, shipment_id, client=None):
        return {
            "details": {
                "id": "SHIP-99",
                "customId": "L42",
                "globalRoute": [
                    {
                        "deleted": False,
                        "address": {"city": "Ripon", "state": "CA", "countryCode": "US"},
                    },
                    {
                        "deleted": False,
                        "address": {"city": "RENO", "state": "NV", "countryCode": "US"},
                    },
                ],
                "carrierOrder": [],
            }
        }

    def fake_upsert_from_turvo(self, **kwargs):
        return {
            "success": True,
            "shipments_row_id": _RATECON_ROW_UUID,
            "created": True,
            "shipment_number": kwargs.get("turvo_shipment_id") or "SHIP-99",
        }

    monkeypatch.setattr(
        "app.services.ratecon_ingress_service.load_id_to_shipment_id_async",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.services.ratecon_ingress_service.get_turvo_shipment_async",
        fake_get,
    )
    monkeypatch.setattr(
        "app.services.ratecon_ingress_service.ShipmentsService.upsert_from_turvo",
        fake_upsert_from_turvo,
    )
    monkeypatch.setattr(
        "app.services.ratecon_ingress_service.RateconSupersedeService.supersede_before_run",
        lambda *a, **k: None,
    )


def _patch_ratecon_graph_mocks(monkeypatch) -> list[dict]:
    """Turvo + lifecycle + upload mocks shared by happy-path test."""

    def fake_load_id_to_shipment(load_id, *, tenant_slug=None):
        return {
            "success": True,
            "load_id": str(load_id),
            "shipment_id": "SHIP-99",
            "message": "ok",
        }

    def fake_upsert_from_turvo(self, **kwargs):
        return {
            "success": True,
            "shipments_row_id": _RATECON_ROW_UUID,
            "created": True,
            "shipment_number": kwargs.get("turvo_shipment_id"),
        }

    monkeypatch.setattr(
        turvo_nodes, "load_id_to_shipment_id_tool", fake_load_id_to_shipment
    )
    monkeypatch.setattr(
        turvo_nodes.ShipmentsService,
        "upsert_from_turvo",
        fake_upsert_from_turvo,
    )
    monkeypatch.setattr(
        turvo_nodes.ShipmentsService,
        "enrich_display_fields_from_turvo_payload",
        fake_upsert_from_turvo,
    )

    def fake_get_shipment(shipment_id, *, tenant_slug=None):
        return {
            "shipment_id": str(shipment_id),
            "details": {
                "globalRoute": [
                    {
                        "deleted": False,
                        "address": {"city": "Ripon", "state": "CA", "countryCode": "US"},
                    },
                    {
                        "deleted": False,
                        "address": {"city": "RENO", "state": "NV", "countryCode": "US"},
                    },
                ],
                "carrierOrder": [],
            },
        }

    monkeypatch.setattr(turvo_nodes, "get_shipment_tool", fake_get_shipment)

    def fake_link_from_route_stops(
        self, stops, *, shipments_row_id, delivery_address_builder=None, shipment_details=None
    ):
        from app.domain.shipment_route_locations import LocationLookup
        from app.services.shipment_location_link_service import (
            ShipmentLocationLinkResult,
        )

        return ShipmentLocationLinkResult(
            pickup_location_id="11111111-1111-1111-1111-111111111111",
            delivery_location_id="22222222-2222-2222-2222-222222222222",
            pickup=LocationLookup(city="Ripon", state_code="CA", country="US"),
            delivery=LocationLookup(city="RENO", state_code="NV", country="US"),
        )

    monkeypatch.setattr(
        turvo_nodes.ShipmentLocationLinkService,
        "link_from_route_stops",
        fake_link_from_route_stops,
    )

    link_calls: list[dict] = []

    def fake_link_shipment_row(self, **kwargs):
        link_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        "app.workflows.nodes.workflow_lifecycle.WorkflowLifecycleService.link_shipment_row",
        fake_link_shipment_row,
    )

    def fake_upload_email_attachments(self, data):
        return {
            "all_succeeded": True,
            "results": [
                {
                    "attachment_id": "att-1",
                    "success": True,
                    "object_key": "ratecon_attachments/ratecon_SHIP-99.pdf",
                    "error_message": None,
                    "original_filename": "Carrier_rate_confirmation.pdf",
                    "document_persist": {
                        "stored": True,
                        "id": "doc-row-1",
                        "shipment_id": data.get("shipments_row_id"),
                    },
                }
            ],
            "ratecon_object_keys": ["ratecon_attachments/ratecon_SHIP-99.pdf"],
        }

    monkeypatch.setattr(
        RateconDocumentService,
        "upload_email_attachments",
        fake_upload_email_attachments,
    )

    return link_calls


@pytest.mark.asyncio
async def test_ratecon_requires_load_id_or_shipment_id():
    service = WorkflowService(WorkflowRepository(), TenantRepository())
    with pytest.raises(Exception, match="load_id"):
        await service.run(
            tenant_slug="t3ra",
            workflow_name="ratecon",
            payload={"event_type": "route_completed"},
        )


@pytest.mark.asyncio
async def test_ratecon_workflow_happy_path_mocked(
    monkeypatch,
    ratecon_ingress_mocks,
    ratecon_lifecycle_stubs,
):
    """Resolve load, link locations, upload ratecon, and persist document metadata."""
    link_calls = _patch_ratecon_graph_mocks(monkeypatch)

    service = WorkflowService(WorkflowRepository(), TenantRepository())
    result = await service.run(
        tenant_slug="t3ra",
        workflow_name="ratecon",
        payload={
            "load_id": "L42",
            "email_id": "email-1",
            "attachments": [{"id": "att-1"}],
        },
    )

    assert len(link_calls) >= 1
    assert all(c["shipments_row_id"] == _RATECON_ROW_UUID for c in link_calls)
    assert result["data"]["shipment_id"] == "SHIP-99"
    assert result["data"]["ratecon_workflow_lifecycle"]["in_workflow_lifecycle"] is True
    assert result["data"]["ratecon_workflow_lifecycle"]["shipments_row_id"] == (
        _RATECON_ROW_UUID
    )
    assert result["data"]["load_id_to_shipment"]["shipment_id"] == "SHIP-99"
    assert result["data"]["load_id_to_shipment"]["success"] is True
    assert result["data"]["load_id_to_shipment"].get("reused") is True
    assert result["data"]["shipments_row_id"] == _RATECON_ROW_UUID
    assert result["data"]["shipment"]["details"]["globalRoute"]
    assert result["data"]["shipment_location_link"]["success"] is True
    assert result["data"]["shipment_location_link"]["pickup_location_id"] == (
        "11111111-1111-1111-1111-111111111111"
    )

    upload = result["data"]["ratecon_s3_upload"]
    assert upload["all_succeeded"] is True
    assert upload["ratecon_object_keys"] == ["ratecon_attachments/ratecon_SHIP-99.pdf"]
    assert upload["results"][0]["document_persist"]["stored"] is True
    assert upload["results"][0]["document_persist"]["id"] == "doc-row-1"
    assert "ratecon_page_count_cache" not in result["data"]
    assert "ratecon_analysis" not in result["data"]
