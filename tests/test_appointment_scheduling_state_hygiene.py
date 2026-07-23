"""Tests for appointment scheduling LangGraph state hygiene helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.appointment_scheduling.metadata_hydration import normalize_appointment_state_data
from app.domain.appointment_scheduling.state_hygiene import (
    INTAKE_CHECKPOINT_STRIP_KEYS,
    strip_intake_checkpoint_data,
    slim_ascend_write_result,
    slim_turvo_write_result,
    slim_weekend_pickup_result,
)
from app.services.appointment_scheduling.ascend_write_service import AscendWriteResult
from app.services.appointment_scheduling.lifecycle_service import (
    LifecycleService,
)
from app.services.appointment_scheduling.turvo_stop_update_service import TurvoWriteResult
from app.domain.appointment_scheduling.metadata_keys import EMAIL_DRAFT


def test_strip_intake_checkpoint_data_removes_vendor_blobs() -> None:
    data = {
        "shipment": {"details": "x" * 1000},
        "ascend_shipment": {"stops": []},
        "customer_id": "123",
        "email_draft": {"to": "a@b.com"},
        "llm_appointment_decision": {"weekend_shifted": False},
        "workflow_lifecycle_status": "processing",
        "workflow_lifecycle_sub_status": "draft_ready",
        "reference_number": "REF-1",
    }
    strip_intake_checkpoint_data(data)
    for key in INTAKE_CHECKPOINT_STRIP_KEYS:
        assert key not in data
    assert data["reference_number"] == "REF-1"


def test_slim_turvo_write_result_omits_response() -> None:
    slim = TurvoWriteResult(
        ok=True,
        updated=True,
        response={"polyline": "x" * 5000},
        stop_name="Costco",
        start_time="2026-07-18T10:30:00",
    ).to_checkpoint_dict()
    assert slim == {
        "ok": True,
        "updated": True,
        "stop_name": "Costco",
        "start_time": "2026-07-18T10:30:00",
    }
    assert "response" not in slim


def test_slim_ascend_write_result_omits_payload_and_response() -> None:
    slim = AscendWriteResult(
        ok=True,
        skipped=True,
        dry_run=True,
        payload={"stop": 1},
        response={"raw": True},
    ).to_checkpoint_dict()
    assert slim == {"ok": True, "skipped": True, "dry_run": True}
    assert "payload" not in slim
    assert "response" not in slim


def test_slim_weekend_pickup_result_omits_vendor_responses() -> None:
    from app.services.appointment_scheduling.weekend_pickup_service import WeekendPickupResult

    slim = WeekendPickupResult(
        ok=True,
        ascend_updated=True,
        turvo_updated=True,
        turvo_pickup_start_time="2026-07-01T08:00:00",
        pickup_stop_name="Pickup",
        ascend_response={"big": "blob"},
        turvo_response={"bigger": "blob"},
    ).to_checkpoint_dict()
    assert slim["ok"] is True
    assert slim["ascend_updated"] is True
    assert slim["turvo_updated"] is True
    assert "ascend_response" not in slim
    assert "turvo_response" not in slim


def test_lifecycle_strip_intake_checkpoint_delegates_to_domain() -> None:
    state = SimpleNamespace(data={"shipment": {"x": 1}, "reference_number": "R1"})
    LifecycleService().strip_intake_checkpoint(state)
    assert "shipment" not in state.data
    assert state.data["reference_number"] == "R1"


def test_slim_turvo_write_result_helper() -> None:
    assert slim_turvo_write_result(ok=False, error="fail") == {"ok": False, "updated": False, "error": "fail"}


def test_slim_ascend_write_result_helper() -> None:
    assert slim_ascend_write_result(ok=True, dry_run=True) == {"ok": True, "dry_run": True}


def test_slim_weekend_pickup_result_helper() -> None:
    assert slim_weekend_pickup_result(ok=True, skipped=True) == {"ok": True, "skipped": True}


def test_normalize_appointment_state_data_promotes_legacy_keys() -> None:
    data = {
        "scheduling_payload": {"reference_number": "REF-1"},
        "llm_scheduling_decision": {"weekend_shifted": True},
        "scheduling_prepare_skip_reason": "duplicate",
        "scheduling_intake_skip_reason": "missing_email",
        "scheduling_failure_reason": "turvo_error",
    }
    normalize_appointment_state_data(data)
    assert data["appointment_payload"] == {"reference_number": "REF-1"}
    assert data["llm_appointment_decision"] == {"weekend_shifted": True}
    assert data["appointment_ingress_skip_reason"] == "duplicate"
    assert data["appointment_intake_skip_reason"] == "missing_email"
    assert data["appointment_failure_reason"] == "turvo_error"
    assert "scheduling_payload" in data


def test_normalize_appointment_state_data_preserves_canonical() -> None:
    data = {
        "appointment_payload": {"reference_number": "CANON"},
        "llm_appointment_decision": {"weekend_shifted": False},
    }
    normalize_appointment_state_data(data)
    assert data["appointment_payload"]["reference_number"] == "CANON"
    assert data["llm_appointment_decision"]["weekend_shifted"] is False


def test_normalize_appointment_state_data_is_idempotent() -> None:
    data = {"scheduling_payload": {"reference_number": "REF-2"}}
    normalize_appointment_state_data(data)
    normalize_appointment_state_data(data)
    assert data["appointment_payload"] == {"reference_number": "REF-2"}
