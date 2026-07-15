"""Opt-in Turvo **sandbox PUT** + app webhook (integration).

**Single opt-in test does two steps**

1. **PUT** sandbox shipment status → route complete (real Turvo + OAuth).
2. **POST** ``/api/listen_turvo_status`` with the ``SHIPMENT_STATUS_UPDATE`` envelope from
   ``tests/e2e/fixtures/main.route_complete_webhook_for_shipment`` (``route_complete_webhook_payload.json``).
   Lifecycle + workflow are
   **faked** so you do not need a matching ``workflow_lifecycle`` row or LangGraph run — this
   step proves the **route, mapper, and dispatch** still work after exercising Turvo.

Turvo may also POST your registered public URL after step 1; this test does **not** rely on
ngrok or Turvo callback latency — step 2 drives the handler directly.

**CI default:** skipped unless ``TURVO_WEBHOOK_TRIGGER_E2E=1``.

**Full stack (real ``pod_lifecycle`` graph):** set ``TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST=1`` and run
``test_listen_turvo_webhook_full_stack_real_workflow_service`` — no dependency override, real
``WorkflowLifecycleService`` + Celery ``run_workflow_async`` (needs DB ``workflow_lifecycle`` row for the
shipment, same as production). HTTP returns ``{"execution_id": ...}``; the test waits 5 minutes (countdown)
then asserts ``workflow_runs`` for that ``execution_id``.

When the webhook or workflow returns a duplicate skip (``skipped: duplicate_route_completed`` or
``result.data.skipped_duplicate_route_completed``), asserts at least one ``workflow_runs`` row exists for
the webhook **shipment_id** and tenant (same axes as dedupe-by-shipment in ``WorkflowRunsService``; skips
``reminder_due`` polling).

When POD is already present (``result.data.pod_exists`` and/or Turvo ``turvo_pod_check`` success with POD), the test
asserts **no** ``send_email`` on that **same** HTTP request (monkeypatch replaces ``app.workflows.nodes.email.send_email_tool``,
the symbol the graph node calls). Celery workers run in a separate process: this does **not** observe reminder-fired emails unless
you run workers in-process / eager mode.

When POD is **missing**, optionally set ``TURVO_POLL_REMINDER_WORKFLOW_RUNS=1`` **or**
``TURVO_REMINDER_RUNS_DB_CHECK=1`` to poll Postgres until enough ``reminder_due`` rows (**requires Celery worker +
Redis**, reminders per ``REMINDER_*_HOURS``). If POD is present, that poll is **skipped** (reminders are not scheduled).
Poll timeout/interval defaults follow those .env values unless ``TURVO_REMINDER_RUNS_POLL_*`` override.

Standalone DB verification only:
``test_workflow_runs_pod_reminders_for_workflow_lifecycle_db`` + ``TURVO_REMINDER_RUNS_DB_CHECK=1``
+ ``TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID``.

Run::

    set TURVO_WEBHOOK_TRIGGER_E2E=1
    set TURVO_WEBHOOK_E2E_APP_USER_ID=deb-test
    uv run pytest tests/test_podlifecycle_webhook_trigger_live.py -m integration -v

    set TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST=1
    set TURVO_REMINDER_RUNS_DB_CHECK=1
    rem or: set TURVO_POLL_REMINDER_WORKFLOW_RUNS=1
    uv run pytest tests/test_podlifecycle_webhook_trigger_live.py::test_listen_turvo_webhook_full_stack_real_workflow_service -v -s

    set TURVO_REMINDER_RUNS_DB_CHECK=1
    set TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID=7cc0f06c-1169-4efa-a4fc-2a663a2b5953
    uv run pytest tests/test_podlifecycle_webhook_trigger_live.py::test_workflow_runs_pod_reminders_for_workflow_lifecycle_db -v -s

**Environment**

+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_E2E`` | ``1`` / ``true`` / ``yes``                                 |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_E2E_APP_USER_ID`` | OAuth lookup; then ``TURVO_LIVE_APP_USER_ID``, ``TURVO_DEFAULT_…`` |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_URL`` | Full PUT URL (default sandbox shipment).                  |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_SHIPMENT_ID`` | If PUT URL has no ``/status/{id}``, webhook POST uses this id. |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_BEARER`` | Override Bearer (skip OAuth).                             |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_COOKIE`` | Optional ``Cookie``                                       |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_TRIGGER_HEADERS_JSON`` | Optional JSON merged into headers                    |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_WEBHOOK_E2E_HTTP_TIMEOUT_S`` | httpx timeout seconds (default ``120``)              |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST`` | ``1`` / ``true`` / ``yes`` — real graph + DB row check |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_POLL_REMINDER_WORKFLOW_RUNS`` | After full-stack listen: poll DB for ``reminder_due`` rows (legacy alias of intent) |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_REMINDER_RUNS_DB_CHECK`` | Standalone **or** same poll after full-stack listen; lifecycle from env or ack |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID`` | UUID for standalone reminder-row check |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_REMINDER_RUNS_EXPECT_COUNT`` | Expected ``reminder_due`` rows (default ``3``) |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_REMINDER_RUNS_POLL_TIMEOUT_S`` | Poll timeout seconds (optional; default from ``REMINDER_*_HOURS`` + ``REMINDER_EXPIRE_GRACE_HOURS``, same horizon as Celery ``expires``) |
+-------------------------------+------------------------------------------------------------+
| ``TURVO_REMINDER_RUNS_POLL_INTERVAL_S`` | Sleep between polls (optional; default scales with that horizon, capped 2–45s) |
+-------------------------------+------------------------------------------------------------+
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_workflow_service
from app.core.config import settings
from app.main import app
from app.repositories.tenants_db_repository import find_tenant_uuid_by_slug
from app.services.turvo_oauth_service import TurvoOAuthService
from app.services.workflow_runs_service import WorkflowRunsService
from tests.e2e.fixtures.main import ROUTE_COMPLETE_WEBHOOK_PAYLOAD
from tests.e2e.fixtures.turvo_webhook_samples import ROUTE_COMPLETE_STATUS_FRAGMENT
from tests.e2e.helpers.countdown_wait import wait_with_countdown
from tests.e2e.helpers.workflow_runs_db import (
    execution_id_from_webhook_response,
    fetch_latest_workflow_run_for_tenant_shipment,
    list_workflow_runs_for_lifecycle_event_type,
)
from tests.e2e.helpers.db_snapshots import fetch_lifecycle_by_id

DEFAULT_E2E_SHIPMENT_ID = 1000324868
DEFAULT_TURVO_STATUS_PUT_URL = (
    f"https://my-sandbox.turvo.com/api/shipments/status/{DEFAULT_E2E_SHIPMENT_ID}"
    "?fullResponse=true"
)

# Fire-and-forget Turvo listen webhook: allow Celery + graph before DB assertions (match pod email e2e horizon).
_LISTEN_TURVO_FULL_STACK_POST_WAIT_S = 300

_POD_REMINDER_DB_EVENT_TYPE = "reminder_due"


def _workflow_runs_tenant_equals_graph_key(*, stored_tenant_uuid: Any, graph_tenant_key: str) -> bool:
    slug_u = find_tenant_uuid_by_slug(graph_tenant_key.strip())
    if slug_u:
        return str(stored_tenant_uuid) == slug_u
    return str(stored_tenant_uuid).strip() == graph_tenant_key.strip()


def _workflow_lifecycle_id_from_listen_ack(ack: Any) -> str | None:
    """``listen_turvo_status`` ack ``result`` is ``WorkflowState`` dump — lifecycle lives under ``data``."""
    if not isinstance(ack, dict):
        return None
    result = ack.get("result")
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if isinstance(data, dict):
        wl = data.get("workflow_lifecycle_id")
        if wl is not None and str(wl).strip():
            return str(wl).strip()
    wl = result.get("workflow_lifecycle_id")
    if wl is not None and str(wl).strip():
        return str(wl).strip()
    return None


def _shipment_id_from_listen_ack(ack: Any | None) -> str | None:
    """Shipment id from ack ``result.data`` (WorkflowState dump)."""
    if not isinstance(ack, dict):
        return None
    result = ack.get("result")
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    sid = data.get("shipment_id")
    if sid is None:
        return None
    s = str(sid).strip()
    return s if s else None


def _skipped_duplicate_route_completed_from_listen_ack(ack: Any | None) -> bool:
    """True when duplicate route_completed was skipped before graph execution."""
    if not isinstance(ack, dict):
        return False
    if ack.get("skipped") == "duplicate_route_completed":
        return True
    result = ack.get("result")
    if not isinstance(result, dict):
        return False
    data = result.get("data")
    if not isinstance(data, dict):
        return False
    return bool(data.get("skipped_duplicate_route_completed"))


def _turvo_documents_pod_found_in_listen_ack(ack: Any | None) -> bool:
    """True when Turvo documents/list succeeded and reported POD (``data.turvo_pod_check``).

    Matches ``check_pod_tool`` / ``check_pod_by_shipment_id`` outcome merged in ``check_existing_pod``.
    """
    if not isinstance(ack, dict):
        return False
    result = ack.get("result")
    if not isinstance(result, dict):
        return False
    data = result.get("data")
    if not isinstance(data, dict):
        return False
    tcp = data.get("turvo_pod_check")
    if not isinstance(tcp, dict):
        return False
    return bool(tcp.get("success")) and bool(tcp.get("pod_exists"))


def _pod_considered_present_from_listen_ack(ack: Any | None) -> bool:
    """True when the graph treated POD as present (no POD reminder schedule on route_completed).

    Prefer Turvo documents/list outcome when present; otherwise ``result.data.pod_exists`` after
    Turvo merge + webhook hints.
    """
    if _turvo_documents_pod_found_in_listen_ack(ack):
        return True
    if not isinstance(ack, dict):
        return False
    result = ack.get("result")
    if not isinstance(result, dict):
        return False
    data = result.get("data")
    if not isinstance(data, dict):
        return False
    return bool(data.get("pod_exists"))


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
            _POD_REMINDER_DB_EVENT_TYPE,
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


def _reminder_poll_enabled_after_listen() -> bool:
    """Either legacy flag or ``TURVO_REMINDER_RUNS_DB_CHECK`` (same poll path after listen)."""
    return _truthy_env("TURVO_POLL_REMINDER_WORKFLOW_RUNS") or _truthy_env(
        "TURVO_REMINDER_RUNS_DB_CHECK"
    )


def _resolve_workflow_lifecycle_id_for_reminder_poll(ack: Any | None) -> str:
    """Env lifecycle wins (pin a known UUID); else parse from listen ack ``result.data``."""
    env_wl = os.environ.get("TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID", "").strip()
    if env_wl:
        return env_wl
    if isinstance(ack, dict):
        got = _workflow_lifecycle_id_from_listen_ack(ack)
        if got:
            return got
    return ""


def _pod_reminder_max_delay_hours() -> float:
    """Max step delay from t3ra ``tenant_settings.pod_lifecycle.reminders`` fixture."""
    from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

    raw = minimal_t3ra_tenant_settings()
    steps = raw["pod_lifecycle"]["reminders"]["steps"]
    return max(float(s["delay_hours"]) for s in steps)


def _reminder_poll_timeout_interval_defaults_from_settings() -> tuple[float, float]:
    """Align poll window with POD reminder schedule in tenant settings + grace.

    Uses the same ``max(countdowns) + REMINDER_EXPIRE_GRACE_HOURS`` horizon as Celery ``expires``,
    plus a small slack for worker execution and ``workflow_runs`` visibility. Probe interval scales
    with that window unless overridden via ``TURVO_REMINDER_RUNS_POLL_INTERVAL_S``.
    """
    max_cd_hours = _pod_reminder_max_delay_hours()
    expire_td = timedelta(hours=max_cd_hours) + timedelta(
        hours=float(settings.REMINDER_EXPIRE_GRACE_HOURS)
    )
    expire_s = float(expire_td.total_seconds())
    timeout_s = expire_s + 180.0

    window_s = max(expire_s, 45.0)
    interval_s = max(2.0, min(45.0, window_s / 45.0))
    return timeout_s, interval_s


def _assert_reminder_due_rows_poll(
    workflow_lifecycle_id: str,
    *,
    tenant_must_match: str | None,
    label: str,
) -> list[dict[str, Any]]:
    expect = _int_env("TURVO_REMINDER_RUNS_EXPECT_COUNT", 3)
    derived_timeout, derived_interval = _reminder_poll_timeout_interval_defaults_from_settings()
    timeout_raw = os.environ.get("TURVO_REMINDER_RUNS_POLL_TIMEOUT_S", "").strip()
    interval_raw = os.environ.get("TURVO_REMINDER_RUNS_POLL_INTERVAL_S", "").strip()
    timeout = float(timeout_raw) if timeout_raw else derived_timeout
    interval = float(interval_raw) if interval_raw else derived_interval
    shipment_expect = os.environ.get("TURVO_REMINDER_RUNS_EXPECT_SHIPMENT_ID", "").strip()

    print(
        "[workflow_runs poll config]",
        f"timeout_s={timeout:.1f} interval_s={interval:.2f}",
        f"(env_override_timeout={bool(timeout_raw)} env_override_interval={bool(interval_raw)}; "
        f"pod_reminder_max_delay_hours={_pod_reminder_max_delay_hours():g} "
        f"REMINDER_EXPIRE_GRACE_HOURS={settings.REMINDER_EXPIRE_GRACE_HOURS})",
    )

    rows = _poll_until_reminder_due_count(
        workflow_lifecycle_id,
        min_count=expect,
        timeout_s=timeout,
        interval_s=interval,
    )
    assert len(rows) >= expect, (
        f"[{label}] Expected >= {expect} workflow_runs {_POD_REMINDER_DB_EVENT_TYPE!r} rows for "
        f"workflow_lifecycle_id={workflow_lifecycle_id!r}; got {len(rows)} after {timeout}s poll. "
        "Celery worker + Redis; tune REMINDER_*_HOURS / REMINDER_EXPIRE_GRACE_HOURS in .env or set "
        "TURVO_REMINDER_RUNS_POLL_TIMEOUT_S / TURVO_REMINDER_RUNS_POLL_INTERVAL_S."
    )
    sample = rows[:expect]
    tenant_expect = os.environ.get("TURVO_REMINDER_RUNS_EXPECT_TENANT_ID", "").strip()
    teff = tenant_expect or (tenant_must_match or "")
    if teff:
        slug_u = find_tenant_uuid_by_slug(teff.strip())
        expect_tid = slug_u if slug_u else teff.strip()
        assert all(str(r["tenant_id"]) == expect_tid for r in sample), [r["tenant_id"] for r in sample]
    if shipment_expect:
        wl_snapshot = fetch_lifecycle_by_id(lifecycle_id=str(workflow_lifecycle_id))
        assert wl_snapshot is not None
        assert str(wl_snapshot.get("shipment_id") or "").strip() == shipment_expect

    print(f"\n[{label}] reminder_due workflow_runs (first {expect} of {len(rows)}):\n{sample!r}\n")
    return rows


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _shipment_id_for_e2e_webhook_body() -> int:
    """Keep POST ``listen_turvo_status`` body aligned with PUT ``…/status/{id}`` when overridden."""
    url = os.environ.get("TURVO_WEBHOOK_TRIGGER_URL", DEFAULT_TURVO_STATUS_PUT_URL).strip()
    m = re.search(r"/status/(\d+)", url)
    if m:
        return int(m.group(1))
    raw = os.environ.get("TURVO_WEBHOOK_TRIGGER_SHIPMENT_ID", "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_E2E_SHIPMENT_ID


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _integration_skip(msg: str) -> None:
    pytest.skip(msg)


def _default_workflow_tenant_id() -> str:
    """Match ``listen_turvo_status`` when ``X-Workflow-Tenant-Id`` is omitted."""
    for candidate in (
        (settings.STUDIO_TENANT_SLUG or "").strip() or None,
    ):
        if candidate:
            return candidate
    return "t3ra"


def _resolve_e2e_tenant_slug() -> str | None:
    for key in (
        "TURVO_WEBHOOK_E2E_TENANT_SLUG",
        "TURVO_WEBHOOK_E2E_APP_USER_ID",
        "TURVO_LIVE_TENANT_SLUG",
        "TURVO_LIVE_APP_USER_ID",
    ):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return (settings.TURVO_DEFAULT_TENANT_SLUG or "").strip() or None


def _merge_optional_env_headers(headers: dict[str, str]) -> None:
    cookie = os.environ.get("TURVO_WEBHOOK_TRIGGER_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    extra = os.environ.get("TURVO_WEBHOOK_TRIGGER_HEADERS_JSON", "").strip()
    if extra:
        obj = json.loads(extra)
        if not isinstance(obj, dict):
            raise ValueError("TURVO_WEBHOOK_TRIGGER_HEADERS_JSON must be a JSON object")
        for k, v in obj.items():
            headers[str(k)] = str(v)


def _oauth_bearer_headers(access_token: str) -> dict[str, str]:
    """Match ``TurvoApiClient._build_headers`` (+ JSON body Content-Type)."""
    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    x_key = (settings.TURVO_X_API_KEY or "").strip()
    if x_key:
        headers["x-api-key"] = x_key
    return headers


async def put_sandbox_shipment_route_complete_status() -> httpx.Response:
    """PUT sandbox shipment status — Bearer from OAuth unless env override."""
    url = os.environ.get("TURVO_WEBHOOK_TRIGGER_URL", DEFAULT_TURVO_STATUS_PUT_URL).strip()
    timeout = _float_env("TURVO_WEBHOOK_E2E_HTTP_TIMEOUT_S", 120.0)

    manual_bearer = os.environ.get("TURVO_WEBHOOK_TRIGGER_BEARER", "").strip()
    if manual_bearer:
        headers = _oauth_bearer_headers(manual_bearer)
    else:
        tenant_slug = _resolve_e2e_tenant_slug()
        if not tenant_slug:
            pytest.skip(
                "Set TURVO_WEBHOOK_E2E_TENANT_SLUG (or TURVO_DEFAULT_TENANT_SLUG in .env) "
                "for Turvo OAuth token lookup."
            )
        oauth = TurvoOAuthService()
        try:
            tokens = await oauth.get_tenant_tokens(tenant_slug)
        except RuntimeError as e:
            pytest.skip(f"Turvo OAuth not configured or DB unreachable: {e}")

        if not tokens or not (tokens.get("access_token") or "").strip():
            pytest.skip(
                f"No OAuth access_token for tenant {tenant_slug!r}; link Turvo in DB "
                "or pass TURVO_WEBHOOK_TRIGGER_BEARER for a one-off run."
            )
        headers = _oauth_bearer_headers(tokens["access_token"].strip())

    _merge_optional_env_headers(headers)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await client.put(url, headers=headers, json=ROUTE_COMPLETE_STATUS_FRAGMENT)

"""
@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_put_sandbox_route_complete_and_listen_turvo_status_ack(monkeypatch):
    # 1) Turvo sandbox accepts route-complete PUT. 2) App acknowledges webhook-shaped POST.
    if not _truthy_env("TURVO_WEBHOOK_TRIGGER_E2E"):
        _integration_skip(
            "Set TURVO_WEBHOOK_TRIGGER_E2E=1 to PUT Turvo sandbox (see module docstring)."
        )

    # put_resp = await put_sandbox_shipment_route_complete_status()
    # assert 200 <= put_resp.status_code < 300, put_resp.text[:2000]

    celery_calls: list[dict[str, Any]] = []

    def _fake_apply_async(*_a: Any, **_kw: Any) -> MagicMock:
        inner = _kw.get("kwargs") or {}
        celery_calls.append(dict(inner))
        m = MagicMock()
        m.id = "test-celery-task-id"
        return m

    monkeypatch.setattr("app.api.v1.webhooks.run_workflow_async.apply_async", _fake_apply_async)

    captured: dict = {}

    class _FakeLifecycle:
        def read_lifecycle(self, tenant_id, workflow_name, shipment_id):
            captured["read"] = {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "shipment_id": shipment_id,
            }
            return {"found": True, "email_thread_id": "  inbox-thread-1  "}

    monkeypatch.setattr(turvo_webhook_module, "WorkflowLifecycleService", _FakeLifecycle)
    shipment_id = _shipment_id_for_e2e_webhook_body()
    webhook_body = route_complete_webhook_for_shipment(shipment_id)
    tenant_expect = _default_workflow_tenant_id()
    with TestClient(app) as client:
        post_resp = client.post(
            "/api/listen_turvo_status",
            json=webhook_body,
        )
    assert post_resp.status_code == 200, post_resp.text
    ack = post_resp.json()
    exec_id = execution_id_from_webhook_response(ack)
    assert exec_id, f"expected execution_id in response body, got {ack!r}"
    assert len(celery_calls) == 1
    q = celery_calls[0]
    assert q["workflow_name"] == "pod_lifecycle"
    assert q["tenant_id"] == tenant_expect
    sid_str = str(shipment_id)
    assert q["payload"]["shipment_id"] == sid_str
    assert q["payload"]["event_type"] == "route_completed"
    assert q["payload"]["thread_id"] == "inbox-thread-1"
    assert captured["read"]["shipment_id"] == sid_str
"""

@pytest.mark.integration
def test_pod_lifecycle_route_complete_turvo_webhook(
    monkeypatch,
    capsys: pytest.CaptureFixture[str],
):
    """Real ``WorkflowService.run`` for ``pod_lifecycle`` via ``listen_turvo_status`` + DB run row.

    Requires a matching ``workflow_lifecycle`` row (handler reads ratecon lifecycle by shipment id).
    Skipped unless ``TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST=1``.

    Asserts no ``send_email`` when ack shows POD present; reminder DB poll only when POD is missing.
    Monkeypatch targets ``app.workflows.nodes.email.send_email_tool`` (bound import used by ``send_email`` node).
    """
    # if not _truthy_env("TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST"):
    #     _integration_skip(
    #         "Set TURVO_LISTEN_WEBHOOK_FULL_STACK_TEST=1 (see module docstring)."
    #     )

    app.dependency_overrides.pop(get_workflow_service, None)

    webhook_body = ROUTE_COMPLETE_WEBHOOK_PAYLOAD
    tenant = _default_workflow_tenant_id()

    send_email_calls: list[dict[str, Any]] = []

    def _spy_send_email(*args: Any, **kwargs: Any) -> None:
        send_email_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(
        "app.workflows.nodes.email.send_email_tool",
        _spy_send_email,
    )

    with TestClient(app) as client:
        post_resp = client.post(
            "/api/v1/webhook/turvo",
            json=webhook_body,
        )

    print(f"\n[listen_turvo full stack] HTTP {post_resp.status_code}\n{post_resp.text[:12000]}\n")

    assert post_resp.status_code == 200, post_resp.text[:6000]
    ack = post_resp.json()
    exec_id = execution_id_from_webhook_response(ack)

    assert exec_id, (
        "Expected JSON to include execution_id (top-level from Celery queue, or legacy ack.result); "
        f"keys={list(ack.keys()) if isinstance(ack, dict) else type(ack)!r}"
    )

    with capsys.disabled():
        wait_with_countdown(
            total_s=_LISTEN_TURVO_FULL_STACK_POST_WAIT_S,
            label="listen_turvo full stack e2e",
        )
    workflow_runs_service = WorkflowRunsService()
    
    row = workflow_runs_service.fetch_workflow_run_by_id(run_id=exec_id)
    assert row is not None, (
        f"No workflow_runs row for execution_id={exec_id!r} after "
        f"{_LISTEN_TURVO_FULL_STACK_POST_WAIT_S}s wait — Celery worker may be down or graph too slow."
    )
    assert _workflow_runs_tenant_equals_graph_key(stored_tenant_uuid=row["tenant_id"], graph_tenant_key=tenant)
    assert row["event_type"] == "route_completed"

    if isinstance(ack.get("result"), dict):
        if _pod_considered_present_from_listen_ack(ack):
            assert not send_email_calls, (
                "[listen_turvo full stack] POD already considered present (Turvo documents and/or "
                f"pod_exists in ack) — send_email must not run on this route_completed request; "
                f"calls={send_email_calls!r}"
            )
            skip_reminder = _reminder_poll_enabled_after_listen()
            print(
                "\n[listen_turvo full stack] POD present — no POD-request email on this invoke "
                "(expected after POD in Turvo / state)."
                + (" Reminder DB poll skipped (no Celery reminder enqueue)." if skip_reminder else "")
                + "\n"
            )

        if _skipped_duplicate_route_completed_from_listen_ack(ack):
            sid_blocked = _shipment_id_from_listen_ack(ack)
            if not sid_blocked and isinstance(ack, dict):
                sid_blocked = str(ack.get("shipment_id") or "").strip() or None
            assert sid_blocked, (
                "[listen_turvo full stack] duplicate skip but shipment_id missing from ack "
                f"(result={(ack.get('result') or {})!r})."
            )
            ship_row = fetch_latest_workflow_run_for_tenant_shipment(tenant, sid_blocked)
            assert ship_row is not None, (
                "[listen_turvo full stack] duplicate route_completed — dedupe expects this shipment to already have "
                f"a workflow_runs anchor; none found for tenant_id={tenant!r} shipment_id={sid_blocked!r} "
                "(see WorkflowRunsService.is_workflow_initial_path_blocked shipment branch)."
            )
            assert _workflow_runs_tenant_equals_graph_key(
                stored_tenant_uuid=ship_row["tenant_id"], graph_tenant_key=tenant
            ), (
                f"[listen_turvo full stack] workflow_runs tenant_id mismatch for shipment={sid_blocked!r}: "
                f"got {ship_row['tenant_id']!r}, expected {tenant!r}. Row={ship_row!r}"
            )
            print(
                "\n[listen_turvo full stack] duplicate route_completed skipped — workflow_runs row for shipment "
                f"(no reminder_due poll):\n{ship_row!r}\n"
            )
        elif _reminder_poll_enabled_after_listen() and not _pod_considered_present_from_listen_ack(
            ack
        ):
            wl = _resolve_workflow_lifecycle_id_for_reminder_poll(ack)
            assert wl, (
                "Reminder poll enabled (TURVO_POLL_REMINDER_WORKFLOW_RUNS or TURVO_REMINDER_RUNS_DB_CHECK) "
                "but workflow_lifecycle_id missing. Set TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID or ensure "
                "ack.result.data.workflow_lifecycle_id exists "
                f"(ack.result keys={list((ack.get('result') or {}).keys()) if isinstance(ack.get('result'), dict) else ack!r})."
            )
            _assert_reminder_due_rows_poll(
                wl,
                tenant_must_match=tenant,
                label="listen_turvo full stack",
            )


@pytest.mark.integration
def test_workflow_runs_pod_reminders_for_workflow_lifecycle_db():
    """Poll DB for ``reminder_due`` rows by ``workflow_lifecycle_id`` (Celery reminder executions).

    Skipped unless ``TURVO_REMINDER_RUNS_DB_CHECK=1``. Requires ``TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID``.

    Example::

        set TURVO_REMINDER_RUNS_DB_CHECK=1
        set TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID=7cc0f06c-1169-4efa-a4fc-2a663a2b5953
        uv run pytest tests/test_podlifecycle_webhook_trigger_live.py::test_workflow_runs_pod_reminders_for_workflow_lifecycle_db -v -s
    """
    if not _truthy_env("TURVO_REMINDER_RUNS_DB_CHECK"):
        _integration_skip("Set TURVO_REMINDER_RUNS_DB_CHECK=1 (see docstring).")

    wl = os.environ.get("TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID", "").strip()
    assert wl, "Set TURVO_REMINDER_RUNS_WORKFLOW_LIFECYCLE_ID to the workflow_lifecycles UUID."

    _assert_reminder_due_rows_poll(
        wl,
        tenant_must_match=None,
        label="pod reminder DB only",
    )
