"""Opt-in E2E: ``driver_assignment`` catch-up reminders without ratecon email or Turvo UI.

**What this exercises**

1. Queue ``run_workflow_async`` with ``event_type=ratecon_completed`` (same Celery entry as production
   after ratecon completes — no Unipile webhook, no Turvo route-complete).
2. Graph runs ``schedule_driver_reminders`` → Celery ``trigger_workflow_reminder`` (catch-up at ``eta=now``
   when pickup is ~25h away).
3. Assert ``workflow_runs`` rows in Postgres.

**Prerequisites (staging/dev DB)**

- Completed **ratecon** lifecycle (``DOCUMENT_PROCESSED``) for the shipment.
- ``shipments`` row, ``load_id``, Unipile ``thread_id`` on that ratecon lifecycle.
- No prior ``ratecon_completed`` driver-assignment run for this shipment (or use a fresh load).
- **Celery worker + Redis** running (same as POD reminder E2E).
- ``tenants.settings.inbound_routing_emails`` for t3ra must parse (valid email list) — worker loads settings from DB.
- Optional: ``driver_assignment.shadow_mode: true`` in tenant settings to avoid real carrier email.

**Run (catch-up at R≈25h — 48h template now, 24h suppressed)**

::

    set DRIVER_ASSIGNMENT_FULL_STACK_E2E=1
    set DRIVER_ASSIGNMENT_E2E_SHIPMENTS_ROW_ID=<uuid>
    set DRIVER_ASSIGNMENT_E2E_SHIPMENT_ID=<turvo_shipment_id>
    set DRIVER_ASSIGNMENT_E2E_LOAD_ID=<load_id>
    set DRIVER_ASSIGNMENT_E2E_RATECON_LC_ID=<completed_ratecon_lifecycle_uuid>
    set DRIVER_ASSIGNMENT_E2E_THREAD_ID=<unipile_thread_id>
    rem optional: default 25 — set 27 to expect catch-up + scheduled 24h (3h gap)
    set DRIVER_ASSIGNMENT_E2E_HOURS_UNTIL_PICKUP=25
    rem poll for reminder_due rows after catch-up Celery fires
    set DRIVER_ASSIGNMENT_REMINDER_DB_CHECK=1
    uv run celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
    uv run pytest tests/e2e/scenarios/test_driver_assignment_catch_up_workflow.py -v -s

**Standalone reminder row check** (after a prior full-stack run)::

    set DRIVER_ASSIGNMENT_REMINDER_RUNS_DB_CHECK=1
    set DRIVER_ASSIGNMENT_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID=<driver_assignment_lc_uuid>
    uv run pytest tests/e2e/scenarios/test_driver_assignment_catch_up_workflow.py::test_workflow_runs_driver_reminder_due_for_lifecycle_db -v -s
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest

from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.domain.tenant_settings.registry import parse_tenant_settings
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService
from tests.e2e.fixtures.driver_assignment_e2e import (
    build_ratecon_completed_payload,
    driver_assignment_e2e_correlation,
    hours_until_pickup_from_env,
)
from tests.e2e.helpers.countdown_wait import wait_with_countdown
from tests.e2e.helpers.db_snapshots import fetch_lifecycle_by_id
from tests.e2e.helpers.workflow_runs_db import list_workflow_runs_for_lifecycle_event_type

_DRIVER_ASSIGNMENT_EVENT = WorkflowRunEventType.RATECON_COMPLETED.value
_REMINDER_EVENT = "reminder_due"
_RUN_WORKFLOW_TASK = "app.tasks.workflows.run_workflow_async"
_POST_START_WAIT_S = 90
_REMINDER_POLL_DEFAULT_TIMEOUT_S = 180.0
_REMINDER_POLL_DEFAULT_INTERVAL_S = 5.0


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _integration_skip(msg: str) -> None:
    pytest.skip(msg)


def _require_correlation() -> dict[str, str]:
    correlation = driver_assignment_e2e_correlation()
    if correlation is None:
        _integration_skip(
            "Set DRIVER_ASSIGNMENT_E2E_SHIPMENTS_ROW_ID, DRIVER_ASSIGNMENT_E2E_SHIPMENT_ID, "
            "DRIVER_ASSIGNMENT_E2E_LOAD_ID, DRIVER_ASSIGNMENT_E2E_RATECON_LC_ID, and "
            "DRIVER_ASSIGNMENT_E2E_THREAD_ID (see module docstring)."
        )
    return correlation


def _assert_tenant_settings_parse(tenant_slug: str) -> None:
    from app.repositories.tenants_db_repository import TenantsDbRepository
    from app.core.db import db_scope

    with db_scope() as repos:
        row = TenantsDbRepository(repos.session).get_by_slug(tenant_slug)
    settings = (row or {}).get("settings") or {}
    try:
        parse_tenant_settings(tenant_slug, settings)
    except Exception as exc:
        pytest.fail(
            f"tenants.settings for {tenant_slug!r} failed validation ({exc}). "
            "The Celery worker loads settings from DB — fix inbound_routing_emails / "
            f"other fields before running this E2E. Current inbound_routing_emails="
            f"{settings.get('inbound_routing_emails')!r}"
        )


def _assert_ratecon_prerequisites(correlation: dict[str, str]) -> None:
    _assert_tenant_settings_parse(correlation["tenant_slug"])
    lifecycle = WorkflowLifecycleService()
    ratecon_id = correlation["ratecon_workflow_lifecycle_id"]
    row = lifecycle.read_lifecycle_row_by_id(ratecon_id)
    if not row:
        pytest.fail(
            f"ratecon lifecycle not found: {ratecon_id!r} — use a completed ratecon lifecycle UUID."
        )
    status = str(row.get("status") or "").strip()
    sub_status = str(row.get("sub_status") or "").strip()
    if status != StatusType.COMPLETED.value or sub_status != StatusSubType.DOCUMENT_PROCESSED.value:
        pytest.fail(
            f"ratecon lifecycle must be COMPLETED + DOCUMENT_PROCESSED; got status={status!r} "
            f"sub_status={sub_status!r} lifecycle_id={ratecon_id!r}"
        )

    runs = WorkflowRunsService()
    if runs.is_ratecon_completed_blocked_for_shipment(
        tenant_id=correlation["tenant_slug"],
        workflow_lifecycle_id=None,
        shipment_id=correlation["shipments_row_id"],
        exclude_run_id=None,
    ):
        _integration_skip(
            "Shipment already has a driver_assignment ratecon_completed run (duplicate gate). "
            "Use a fresh shipment/load or clear the prior run for E2E."
        )


def _poll_until_reminder_due_count(
    workflow_lifecycle_id: str,
    *,
    min_count: int,
    timeout_s: float,
    interval_s: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + max(timeout_s, 1.0)
    interval_s = max(interval_s, 0.5)
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = list_workflow_runs_for_lifecycle_event_type(
            workflow_lifecycle_id,
            _REMINDER_EVENT,
        )
        print(
            "[workflow_runs poll]",
            f"lifecycle_id={workflow_lifecycle_id}",
            f"reminder_due_rows={len(last)} need={min_count}",
        )
        if len(last) >= min_count:
            return last
        time.sleep(interval_s)
    return last


def _assert_reminder_due_rows_poll(
    workflow_lifecycle_id: str,
    *,
    label: str,
) -> list[dict[str, Any]]:
    expect = _int_env("DRIVER_ASSIGNMENT_REMINDER_RUNS_EXPECT_COUNT", 1)
    timeout = _float_env(
        "DRIVER_ASSIGNMENT_REMINDER_RUNS_POLL_TIMEOUT_S",
        _REMINDER_POLL_DEFAULT_TIMEOUT_S,
    )
    interval = _float_env(
        "DRIVER_ASSIGNMENT_REMINDER_RUNS_POLL_INTERVAL_S",
        _REMINDER_POLL_DEFAULT_INTERVAL_S,
    )
    rows = _poll_until_reminder_due_count(
        workflow_lifecycle_id,
        min_count=expect,
        timeout_s=timeout,
        interval_s=interval,
    )
    assert len(rows) >= expect, (
        f"[{label}] Expected >= {expect} workflow_runs {_REMINDER_EVENT!r} rows for "
        f"workflow_lifecycle_id={workflow_lifecycle_id!r}; got {len(rows)} after {timeout}s poll. "
        "Ensure Celery worker + Redis are running; catch-up enqueues an immediate reminder when "
        "DRIVER_ASSIGNMENT_E2E_HOURS_UNTIL_PICKUP is ~25."
    )
    print(f"\n[{label}] reminder_due workflow_runs (first {expect} of {len(rows)}):\n{rows[:expect]!r}\n")
    return rows


@pytest.mark.integration
@pytest.mark.driver_assignment_catch_up_workflow
def test_driver_assignment_ratecon_completed_catch_up_full_stack(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Real graph + Celery: ``ratecon_completed`` → schedule catch-up → optional ``reminder_due`` poll."""
    if not _truthy_env("DRIVER_ASSIGNMENT_FULL_STACK_E2E"):
        _integration_skip("Set DRIVER_ASSIGNMENT_FULL_STACK_E2E=1 (see module docstring).")

    correlation = _require_correlation()
    _assert_ratecon_prerequisites(correlation)

    hours_until_pickup = hours_until_pickup_from_env(default=25.0)
    execution_id = str(uuid.uuid4())
    payload = build_ratecon_completed_payload(
        correlation,
        hours_until_pickup=hours_until_pickup,
        execution_id=execution_id,
    )

    print(
        "\n[driver_assignment e2e] enqueue ratecon_completed",
        f"execution_id={execution_id}",
        f"hours_until_pickup={hours_until_pickup}",
        f"shipment_id={correlation['shipment_id']}",
        f"ratecon_lc={correlation['ratecon_workflow_lifecycle_id']}\n",
    )

    # Import celery_app (not workflows) so task modules finish loading before enqueue.
    from app.celery_app import celery_app

    celery_app.send_task(
        _RUN_WORKFLOW_TASK,
        kwargs={
            "tenant_slug": correlation["tenant_slug"],
            "workflow_name": "driver_assignment",
            "payload": payload,
        },
    )

    with capsys.disabled():
        wait_with_countdown(
            total_s=_POST_START_WAIT_S,
            label="driver_assignment ratecon_completed e2e",
        )

    runs = WorkflowRunsService()
    row = runs.fetch_workflow_run_by_id(run_id=execution_id)
    assert row is not None, (
        f"No workflow_runs row for execution_id={execution_id!r} after {_POST_START_WAIT_S}s — "
        "Celery worker may be down or graph failed before record."
    )
    assert row["event_type"] == _DRIVER_ASSIGNMENT_EVENT, row

    driver_lc_id = str(row.get("workflow_lifecycle_id") or "").strip()
    assert driver_lc_id, f"workflow_runs row missing workflow_lifecycle_id: {row!r}"

    wl = fetch_lifecycle_by_id(lifecycle_id=driver_lc_id)
    assert wl is not None, f"No workflow_lifecycles row for {driver_lc_id!r}"
    assert wl.get("workflow_name") == "driver_assignment", wl

    print(
        "\n[driver_assignment e2e] ratecon_completed run OK",
        f"driver_lifecycle_id={driver_lc_id}",
        f"hours_until_pickup={hours_until_pickup}\n",
    )

    if _truthy_env("DRIVER_ASSIGNMENT_REMINDER_DB_CHECK"):
        _assert_reminder_due_rows_poll(
            driver_lc_id,
            label="driver_assignment catch-up e2e",
        )


@pytest.mark.integration
@pytest.mark.driver_assignment_catch_up_workflow
def test_workflow_runs_driver_reminder_due_for_lifecycle_db() -> None:
    """Poll ``reminder_due`` rows for a pinned driver_assignment lifecycle (standalone DB check)."""
    if not _truthy_env("DRIVER_ASSIGNMENT_REMINDER_RUNS_DB_CHECK"):
        _integration_skip(
            "Set DRIVER_ASSIGNMENT_REMINDER_RUNS_DB_CHECK=1 and "
            "DRIVER_ASSIGNMENT_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID."
        )

    wl = os.environ.get("DRIVER_ASSIGNMENT_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID", "").strip()
    if not wl:
        pytest.fail(
            "Set DRIVER_ASSIGNMENT_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID to a driver_assignment "
            "workflow_lifecycle UUID."
        )

    snapshot = fetch_lifecycle_by_id(lifecycle_id=wl)
    assert snapshot is not None, f"No workflow_lifecycles row for {wl!r}"
    assert snapshot.get("workflow_name") == "driver_assignment", snapshot

    _assert_reminder_due_rows_poll(wl, label="driver_assignment reminder DB check")
