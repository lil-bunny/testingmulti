"""Tests for cached ratecon extraction loading in pod lifecycle."""

from __future__ import annotations

from types import SimpleNamespace

from app.tools import pod as pod_tools
from app.workflows.graph.routers import ratecon_cache_router
from app.workflows.nodes import pod as pod_nodes

_SHIPMENTS_ROW_ID = "e76d2aee-1234-5678-9abc-def012345678"
_TEST_PAYLOAD = {
    "tenant_id": "t3ra",
    "shipment_id": "1000324895",
    "shipments_row_id": _SHIPMENTS_ROW_ID,
}


def test_load_ratecon_analysis_cache_hit(monkeypatch):
    findings = {
        "extracted_fields": {"broker_name": "Acme Broker", "po_number": "123"},
        "metadata": {"pages_processed": 1},
    }

    monkeypatch.setattr(
        pod_tools,
        "read_ratecon_extraction",
        lambda row_id: {
            "found": True,
            "row": {
                "id": "analysis-uuid-1",
                "results": findings,
                "confidence_score": 0.9,
                "document_id": "doc-1",
            },
        },
    )

    out = pod_tools.load_ratecon_analysis(_TEST_PAYLOAD)

    assert out["success"] is True
    assert out["cached"] is True
    assert out["findings"] == findings
    assert out["confidence_score"] == 0.9
    assert out["document_analysis_id"] == "analysis-uuid-1"


def test_load_ratecon_analysis_missing_row(monkeypatch):
    monkeypatch.setattr(
        pod_tools,
        "read_ratecon_extraction",
        lambda row_id: {"found": False},
    )

    out = pod_tools.load_ratecon_analysis(_TEST_PAYLOAD)

    assert out["success"] is False
    assert out["skipped"] is True
    assert out["reason"] == "no_ratecon_extraction"


def test_load_ratecon_analysis_missing_extracted_fields(monkeypatch):
    monkeypatch.setattr(
        pod_tools,
        "read_ratecon_extraction",
        lambda row_id: {
            "found": True,
            "row": {
                "id": "analysis-uuid-2",
                "results": {"metadata": {"pages_processed": 0}},
            },
        },
    )

    out = pod_tools.load_ratecon_analysis(_TEST_PAYLOAD)

    assert out["success"] is False
    assert out["skipped"] is True
    assert out["reason"] == "no_ratecon_extraction"


def test_load_ratecon_analysis_node_sets_cache_pointer(monkeypatch):
    monkeypatch.setattr(
        pod_nodes,
        "load_ratecon_analysis_tool",
        lambda data: {
            "success": True,
            "shipment_id": "1000324895",
            "findings": {"extracted_fields": {"broker_name": "Acme"}},
            "document_analysis_id": "cached-row-1",
            "cached": True,
        },
    )

    state = SimpleNamespace(data={"shipment_id": "1000324895"})
    pod_nodes.load_ratecon_analysis(state)

    assert state.data["ratecon_analysis_results"]["cached"] is True
    assert state.data["document_analysis_ratecon"] == {
        "stored": True,
        "id": "cached-row-1",
        "source": "cache",
    }


def test_ratecon_cache_router_ready_and_missing():
    ready_state = SimpleNamespace(
        data={
            "ratecon_analysis_results": {
                "success": True,
                "findings": {"extracted_fields": {"po_number": "1"}},
            }
        }
    )
    assert ratecon_cache_router(ready_state) == "ready"

    missing_state = SimpleNamespace(
        data={
            "ratecon_analysis_results": {
                "success": False,
                "skipped": True,
                "reason": "no_ratecon_extraction",
            }
        }
    )
    assert ratecon_cache_router(missing_state) == "missing"
