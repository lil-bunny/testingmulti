"""Router tests for manual POD upload workflow branches."""

from __future__ import annotations

from types import SimpleNamespace

from app.workflows.graph.routers import (
    event_type_router,
    manual_tms_upload_router,
    ratecon_cache_router,
    read_workflow_lifecycle_router,
    shipment_router,
)


def _state(**data):
    return SimpleNamespace(data=data)


def test_event_type_router_manual_pod_upload():
    state = _state(event_type="manual_pod_upload")
    assert event_type_router(state) == "manual_pod_upload"


def test_read_workflow_lifecycle_router_manual_found():
    state = _state(
        event_type="manual_pod_upload",
        workflow_lifecycle_payload={"found": True, "lifecycle_id": "wl-1"},
    )
    assert read_workflow_lifecycle_router(state) == "is_found"


def test_shipment_router_manual_valid_status():
    state = _state(
        event_type="manual_pod_upload",
        shipment={"details": {"status": {"code": {"key": "2116"}}}},
    )
    assert shipment_router(state) == "manual_pod_valid"


def test_ratecon_cache_router_ready():
    state = _state(
        ratecon_analysis_results={
            "success": True,
            "findings": {"extracted_fields": {"broker_name": "Broker"}},
        }
    )
    assert ratecon_cache_router(state) == "ready"


def test_ratecon_cache_router_missing_when_skipped():
    state = _state(
        ratecon_analysis_results={
            "success": False,
            "skipped": True,
            "reason": "no_ratecon_extraction",
        }
    )
    assert ratecon_cache_router(state) == "missing"


def test_shipment_router_manual_invalid_status():
    state = _state(
        event_type="manual_pod_upload",
        shipment={"details": {"status": {"code": {"key": "9999"}}}},
    )
    assert shipment_router(state) == "invalid_shipment_status"


def test_manual_tms_upload_router_continue_on_uploaded():
    state = _state(pod_tms_upload_outcome="uploaded")
    assert manual_tms_upload_router(state) == "continue"


def test_manual_tms_upload_router_continue_on_skipped():
    state = _state(pod_tms_upload_outcome="skipped")
    assert manual_tms_upload_router(state) == "continue"


def test_manual_tms_upload_router_stop_on_failed():
    state = _state(pod_tms_upload_outcome="failed")
    assert manual_tms_upload_router(state) == "stop"


def test_manual_tms_upload_router_stop_when_outcome_missing():
    state = _state()
    assert manual_tms_upload_router(state) == "stop"
