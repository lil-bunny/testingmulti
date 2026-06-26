"""Unit tests for routing-guide lifecycle routing, domain, and persistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.domain.gelita.routing_guide_lifecycle import (
    mark_routing_guide_reminders_scheduled_for_attempt,
    routing_guide_attempt_from_metadata,
    routing_guide_attempt_from_state,
    routing_guide_attempt_is_stale,
    routing_guide_order_matches_lifecycle,
    routing_guide_reminders_scheduled_for_attempt,
    routing_guide_same_attempt_thread_conflict,
    routing_guide_thread_is_retired,
    gelita_routing_guide_sub_status_for,
    sync_routing_guide_attempt_to_state,
)
from app.domain.load_tendering_settings import routing_guide_max_attempts
from app.models.status import StatusSubType
from app.services.routing_guide_lifecycle_service import RoutingGuideLifecycleService
from app.tools.routing_guide_carrier import build_carrier_note
from app.workflows.graph.routers import routing_guide_router, tender_status_router
from app.workflows.nodes.routing_guide import (
    advance_carrier_routing_guide,
    evaluate_reject_routing_guide,
    evaluate_timeout_routing_guide,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _tenant_settings() -> dict:
    return load_tenant_settings_dev("gelita")


def _state(
    *,
    load_type: str = "FTL",
    attempt: int | None = None,
    **data_extra,
):
    data = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "tender_id": TENDER_UUID,
        "tenant_settings": _tenant_settings(),
        "tender": {"load_type": load_type},
    }
    if attempt is not None:
        data["routing_guide_attempt"] = attempt
        data["workflow_lifecycle_metadata"] = {"routing_guide_attempt": attempt}
    data.update(data_extra)
    return SimpleNamespace(tenant_id=TENANT_UUID, execution_id=RUN_UUID, data=data)


def test_sub_status_mapper_tenant_and_carrier():
    assert (
        gelita_routing_guide_sub_status_for(1, "tenant")
        == StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_1
    )
    assert (
        gelita_routing_guide_sub_status_for(2, "carrier")
        == StatusSubType.TENDER_SENT_TO_CARRIER_2
    )
    assert (
        gelita_routing_guide_sub_status_for(99, "tenant")
        == StatusSubType.TENDER_SENT_TO_TENANT_FOR_CARRIER_3
    )


def test_routing_guide_attempt_from_metadata_defaults_to_one():
    assert routing_guide_attempt_from_metadata({}) == 1
    assert routing_guide_attempt_from_metadata(None) == 1
    assert routing_guide_attempt_from_metadata({"routing_guide_attempt": 2}) == 2


def test_routing_guide_attempt_from_state_prefers_top_level_key():
    data = {"routing_guide_attempt": 3, "workflow_lifecycle_metadata": {"routing_guide_attempt": 1}}
    assert routing_guide_attempt_from_state(data) == 3


def test_routing_guide_max_attempts_reads_gelita_fixture():
    state = _state()
    assert routing_guide_max_attempts(state) == 3


def test_routing_guide_max_attempts_clamps_above_ceiling():
    settings = _tenant_settings()
    settings["load_tendering"]["ftl"]["max_attempts"] = 9
    state = _state()
    state.data["tenant_settings"] = settings
    assert routing_guide_max_attempts(state) == 3


def test_routing_guide_router_ltl_terminal():
    state = _state(load_type="LTL")
    assert routing_guide_router(state) == "ltl_terminal"


def test_routing_guide_router_advance_when_below_max():
    state = _state(load_type="FTL", attempt=1)
    assert routing_guide_router(state) == "advance"


def test_routing_guide_router_exhausted_at_max():
    state = _state(load_type="FTL", attempt=3)
    assert routing_guide_router(state) == "exhausted"


def test_evaluate_nodes_set_routing_guide_reason():
    reject_state = _state()
    evaluate_reject_routing_guide(reject_state)
    assert reject_state.data["routing_guide_reason"] == "carrier_rejected"

    timeout_state = _state()
    evaluate_timeout_routing_guide(timeout_state)
    assert timeout_state.data["routing_guide_reason"] == "carrier_timeout"


@patch("app.workflows.nodes.routing_guide.RoutingGuideLifecycleService")
def test_advance_carrier_routing_guide_delegates_to_service(mock_service_cls):
    mock_service = MagicMock()
    mock_service.advance.return_value = 2
    mock_service_cls.return_value = mock_service

    state = _state(attempt=1, routing_guide_reason="carrier_rejected")
    advance_carrier_routing_guide(state)

    mock_service.advance.assert_called_once_with(
        state, reason="carrier_rejected"
    )
    assert state.data["routing_guide_failover"] is True


@patch("app.services.routing_guide_lifecycle_service.run_with_repos")
def test_routing_guide_lifecycle_service_advance_increments(mock_run):
    repos = MagicMock()
    repos.workflow_lifecycles.read_row_by_id.return_value = {
        "metadata": {"routing_guide_attempt": 1},
    }

    def _fake_run(fn):
        return fn(repos)

    mock_run.side_effect = _fake_run

    state = _state(attempt=1)
    service = RoutingGuideLifecycleService()
    new_attempt = service.advance(state, reason="carrier_rejected")

    assert new_attempt == 2
    repos.workflow_lifecycles.set_routing_guide_attempt.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        attempt=2,
    )
    assert state.data["routing_guide_attempt"] == 2


def test_carrier_note_first_and_subsequent_attempts():
    email = "carrier@example.com"
    assert build_carrier_note(1, email) == f"Note: Use carrier {email}"
    assert "Carrier 1 did not respond" in build_carrier_note(2, email)


def test_tender_status_router_stale_routing_guide_reminder():
    state = _state()
    state.data["stale_routing_guide_reminder"] = True
    assert tender_status_router(state) == "completed"


def test_ltl_routing_guide_router_non_regression():
    state = _state(load_type="LTL", attempt=1)
    assert routing_guide_router(state) == "ltl_terminal"


def test_read_tender_row_stale_routing_guide_skip():
    from app.workflows.nodes.tenders import read_tender_row

    state = _state(load_type="FTL", attempt=2)
    state.data["event_type"] = "reminder_due"
    state.data["routing_guide_attempt"] = 1

    tender_bundle = {
        "tender": {
            "delivery_date": "2026-06-25",
            "metadata": {"po_number": "347892"},
        },
        "products": [],
    }
    lifecycle_row = {
        "status": "processing",
        "metadata": {"routing_guide_attempt": 2},
    }

    with patch(
        "app.workflows.nodes.tenders.TenderService"
    ) as mock_tender_service_cls, patch(
        "app.workflows.nodes.tenders.WorkflowLifecycleService"
    ) as mock_lifecycle_service_cls:
        mock_tender_service = MagicMock()
        mock_tender_service.read_order.return_value = tender_bundle
        mock_tender_service_cls.return_value = mock_tender_service

        mock_lifecycle_service = MagicMock()
        mock_lifecycle_service.read_lifecycle_row_by_id.return_value = lifecycle_row
        mock_lifecycle_service_cls.return_value = mock_lifecycle_service

        read_tender_row(state)

    assert state.data.get("stale_routing_guide_reminder") is True


def test_sync_routing_guide_attempt_to_state():
    data: dict = {}
    sync_routing_guide_attempt_to_state(data, attempt=2)
    assert data["routing_guide_attempt"] == 2


def test_routing_guide_attempt_is_stale_behind_and_ahead():
    assert routing_guide_attempt_is_stale(1, 2) is True
    assert routing_guide_attempt_is_stale(3, 2) is True
    assert routing_guide_attempt_is_stale(2, 2) is False
    assert routing_guide_attempt_is_stale("bad", 2) is False


def test_routing_guide_thread_is_retired():
    assert routing_guide_thread_is_retired(1, 2) is True
    assert routing_guide_thread_is_retired(2, 2) is False
    assert routing_guide_thread_is_retired(3, 2) is False


def test_routing_guide_same_attempt_thread_conflict():
    assert routing_guide_same_attempt_thread_conflict(
        linked_thread="thread-a",
        incoming_thread="thread-b",
    )
    assert not routing_guide_same_attempt_thread_conflict(
        linked_thread="thread-a",
        incoming_thread="thread-a",
    )
    assert not routing_guide_same_attempt_thread_conflict(
        linked_thread=None,
        incoming_thread="thread-a",
    )


def test_routing_guide_order_matches_lifecycle():
    assert routing_guide_order_matches_lifecycle("t1", "t1")
    assert not routing_guide_order_matches_lifecycle("t1", "t2")


def test_routing_guide_reminders_scheduled_for_attempt():
    meta = mark_routing_guide_reminders_scheduled_for_attempt(attempt=2)
    assert routing_guide_reminders_scheduled_for_attempt(meta, 2)
    assert not routing_guide_reminders_scheduled_for_attempt(meta, 1)


@patch("app.services.routing_guide_lifecycle_service.run_with_repos")
def test_routing_guide_advance_noop_when_live_ahead(mock_run):
    repos = MagicMock()
    repos.workflow_lifecycles.read_row_by_id.return_value = {
        "metadata": {"routing_guide_attempt": 2},
    }

    def _fake_run(fn):
        return fn(repos)

    mock_run.side_effect = _fake_run

    state = _state(attempt=1)
    service = RoutingGuideLifecycleService()
    new_attempt = service.advance(state, reason="carrier_timeout")

    assert new_attempt == 2
    repos.workflow_lifecycles.set_routing_guide_attempt.assert_not_called()
    assert state.data["routing_guide_attempt"] == 2


@patch("app.services.routing_guide_lifecycle_service.run_with_repos")
def test_routing_guide_advance_race_single_increment(mock_run):
    repos = MagicMock()
    repos.workflow_lifecycles.read_row_by_id.return_value = {
        "metadata": {"routing_guide_attempt": 1},
    }

    def _fake_run(fn):
        return fn(repos)

    mock_run.side_effect = _fake_run

    state = _state(attempt=1)
    service = RoutingGuideLifecycleService()
    new_attempt = service.advance(state, reason="carrier_rejected")

    assert new_attempt == 2
    repos.workflow_lifecycles.set_routing_guide_attempt.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        attempt=2,
    )
