"""
HTTP-level tests for ``POST /api/webhook/unipile`` (ratecon vs pod_lifecycle routing).

Uses the real FastAPI app and route handler (including ``WorkflowClassifierService`` logic
via ``app.api.routes.unipile_mail_thread_capture``). Default tests override
``WorkflowService`` so CI stays offline.

**Full stack (real workflow):** set ``UNIPILE_WEBHOOK_FULL_STACK_TEST=1`` and run
``test_unipile_webhook_full_stack_real_workflow_service`` — no dependency override; asserts
HTTP 200, ``execution_id`` on the JSON body (same UUID queued for Celery), waits 30s for the
worker, then asserts a matching ``workflow_runs`` row.
"""

from __future__ import annotations

import os
from pprint import pformat
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_workflow_service
from app.core.config import settings
from app.main import app
from app.models.document import DocumentType
from app.services import workflow_runs_service
from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD
from tests.e2e.helpers.countdown_wait import wait_with_countdown
from tests.e2e.helpers.db_snapshots import (
    fetch_documents_for_shipment,
    fetch_lifecycle_by_id,
    fetch_lifecycles_for_email_thread,
)
from tests.e2e.helpers.workflow_runs_db import execution_id_from_webhook_response

_RATECON_E2E_TENANT_ID = "t3ra"
_RATECON_DOC_TYPE = DocumentType.RATECON.value
_POST_WEBHOOK_FULL_STACK_WAIT_S = 20


def _fail_ratecon_e2e(reason: str) -> None:
    print(f"\n[ratecon e2e DB check FAILED]\n{reason}\n")
    pytest.fail(reason)


def _report_check(ok: bool, label: str, detail: str | None = None) -> None:
    icon = "✓" if ok else "✗"
    if detail:
        print(f"{icon} {label}: {detail}")
    else:
        print(f"{icon} {label}")


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"}


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.pop(get_workflow_service, None)


def test_webhook_rejects_invalid_bearer():
    """Wrong ``Authorization`` is denied; handler currently maps that to 500 (broad ``except``)."""
    with TestClient(app) as client:
        r = client.post(
            "/api/webhook/unipile",
            json=RATECON_WEBHOOK_PAYLOAD,
            headers={"Authorization": "Bearer wrong-secret"},
        )
    assert r.status_code == 401
    detail = r.json().get("detail", "")
    assert "401" in str(detail) or "Unauthorized" in str(detail)


def test_webhook_invalid_webhook_name_returns_message_and_skips_workflow():
    bad = {**RATECON_WEBHOOK_PAYLOAD, "webhook_name": "not_registered_webhook_name"}

    with TestClient(app) as client:
        r = client.post("/api/webhook/unipile", json=bad, headers=_auth_headers())

    assert r.status_code == 200, r.text
    assert r.json() == {"message": "invalid webhook"}


def assert_ratecon_pre_webhook_db_state(*, payload: dict, tenant_id: str) -> None:
    """
    Before snapshot:
    1) payload has thread_id
    2) no workflow_lifecycles row for this thread
    3) if lifecycle rows already exist, no ratecon docs for related shipments
    """
    print("\n[before snapshot]\n")

    thread_id = str(payload.get("thread_id") or "").strip()
    _report_check(bool(thread_id), "payload has non-empty thread_id", repr(thread_id))

    if not thread_id:
        _fail_ratecon_e2e(
            "Before snapshot failed: ratecon webhook payload has no non-empty `thread_id`."
        )

    lifecycles = fetch_lifecycles_for_email_thread(tenant_id=tenant_id, thread_id=thread_id)

    _report_check(
        not lifecycles,
        "no workflow_lifecycles rows exist for this thread",
        f"count={len(lifecycles)}",
    )

    print(
        "[before snapshot data]\n"
        f"  tenant_id={tenant_id!r}\n"
        f"  thread_id={thread_id!r}\n"
        f"  lifecycle_count={len(lifecycles)}"
    )

    if not lifecycles:
        print("\n[before snapshot OK]\n")
        return

    parts: list[str] = [
        "Before snapshot failed (check 2): expected no `workflow_lifecycles` row for this Unipile "
        f"thread, but found {len(lifecycles)} row(s) where `email_thread_id` matches `thread_id`.",
        f"  tenant_id={tenant_id!r} thread_id={thread_id!r}",
    ]

    for lc in lifecycles:
        parts.append(
            f"  lifecycle id={lc.get('id')!r} workflow_name={lc.get('workflow_name')!r} "
            f"shipment_id={lc.get('shipment_id')!r}"
        )

    shipment_ids = {
        str(lc.get("shipment_id") or "").strip()
        for lc in lifecycles
        if str(lc.get("shipment_id") or "").strip()
    }

    ratecon_hits: list[str] = []
    for sid in sorted(shipment_ids):
        docs = fetch_documents_for_shipment(shipment_id=sid)
        ratecon_rows = [d for d in docs if str(d.get("type") or "").strip() == _RATECON_DOC_TYPE]

        ok = not ratecon_rows
        _report_check(
            ok,
            f"no ratecon documents for shipment_id={sid}",
            f"ratecon_count={len(ratecon_rows)}",
        )

        if ratecon_rows:
            ratecon_hits.append(
                f"  shipment_id={sid!r}: found {len(ratecon_rows)} document(s) with type={_RATECON_DOC_TYPE!r} "
                f"(ids={[d.get('id') for d in ratecon_rows]})"
            )

    if ratecon_hits:
        parts.append(
            "Before snapshot failed (check 3): lifecycle row(s) already exist for this thread, and "
            f"at least one `documents` row has doc type (column `type`) {_RATECON_DOC_TYPE!r} for "
            "the related shipment(s) — clean DB state required."
        )
        parts.extend(ratecon_hits)

    _fail_ratecon_e2e("\n".join(parts))


def assert_ratecon_post_webhook_db_state(*, execution_id: str) -> dict[str, Any]:
    """
    After snapshot:
    1) workflow_runs row exists
    2) workflow_lifecycle_id exists
    3) workflow_lifecycles row exists
    4) shipment_id exists
    5) ratecon document exists for shipment
    """
    print("\n[after snapshot]\n")

    exec_id = str(execution_id or "").strip()
    _report_check(bool(exec_id), "execution_id is present", repr(exec_id))

    if not exec_id:
        _fail_ratecon_e2e(
            "After snapshot failed (check 1): `execution_id` is missing or empty, cannot look up "
            "`workflow_runs`."
        )

    run_row = workflow_runs_service.fetch_workflow_run_by_id(run_id=exec_id)
    _report_check(run_row is not None, "workflow_runs row exists", pformat(run_row, width=120))

    if run_row is None:
        _fail_ratecon_e2e(
            "After snapshot failed (check 1): no row in `workflow_runs` for this `execution_id` "
            f"(expected PK `workflow_runs.id` = graph execution id).\n  execution_id={exec_id!r}"
        )

    wl_id = str(run_row.get("workflow_lifecycle_id") or "").strip()
    _report_check(bool(wl_id), "workflow_lifecycle_id exists", repr(wl_id))

    if not wl_id:
        _fail_ratecon_e2e(
            "After snapshot failed (check 2): `workflow_runs` row exists but `workflow_lifecycle_id` "
            "is null or empty — cannot resolve lifecycle / shipment.\n"
            f"  execution_id={exec_id!r}\n"
            f"  workflow_runs row={run_row!r}"
        )

    lc = fetch_lifecycle_by_id(lifecycle_id=wl_id)
    _report_check(lc is not None, "workflow_lifecycles row exists", pformat(lc, width=120))

    if lc is None:
        _fail_ratecon_e2e(
            "After snapshot failed (check 2): no row in `workflow_lifecycles` for the id referenced "
            "by `workflow_runs.workflow_lifecycle_id`.\n"
            f"  execution_id={exec_id!r}\n"
            f"  workflow_lifecycle_id={wl_id!r}"
        )

    shipment_id = str(lc.get("shipment_id") or "").strip()
    _report_check(bool(shipment_id), "shipment_id exists", repr(shipment_id))

    if not shipment_id:
        _fail_ratecon_e2e(
            "After snapshot failed (check 3): `workflow_lifecycles` row exists but `shipment_id` is "
            "null or empty — cannot verify `documents`.\n"
            f"  execution_id={exec_id!r}\n"
            f"  workflow_lifecycle_id={wl_id!r}\n"
            f"  lifecycle row={lc!r}"
        )

    docs = fetch_documents_for_shipment(shipment_id=shipment_id)
    ratecon_docs = [d for d in docs if str(d.get("type") or "").strip() == _RATECON_DOC_TYPE]

    _report_check(
        bool(ratecon_docs),
        "ratecon document exists",
        f"ratecon_count={len(ratecon_docs)}",
    )

    print(
        "[after snapshot data]\n"
        f"  execution_id={exec_id!r}\n"
        f"  workflow_run_row={pformat(run_row, width=120)}\n"
        f"  workflow_lifecycle_id={wl_id!r}\n"
        f"  lifecycle_row={pformat(lc, width=120)}\n"
        f"  shipment_id={shipment_id!r}\n"
        f"  shipment_document_count={len(docs)}\n"
        f"  ratecon_document_ids={[d.get('id') for d in ratecon_docs]}"
    )

    if not ratecon_docs:
        types_found = sorted({str(d.get("type") or "") for d in docs if d.get("type") is not None})
        _fail_ratecon_e2e(
            "After snapshot failed (check 4): no `documents` row with doc type (column `type`) "
            f"{_RATECON_DOC_TYPE!r} for this shipment after the workflow.\n"
            f"  execution_id={exec_id!r}\n"
            f"  shipment_id={shipment_id!r}\n"
            f"  document rows for shipment: count={len(docs)} type_values_found={types_found!r}"
        )

    print(
        f"\n[ratecon e2e DB checks OK] execution_id={exec_id!r} shipment_id={shipment_id!r} "
        f"ratecon_documents={len(ratecon_docs)}\n"
    )
    return run_row


@pytest.mark.integration
def test_ratecon_email_received_unipile_webhook(
    capsys: pytest.CaptureFixture[str],
):
    # Keep real workflow service override disabled for this integration path.
    app.dependency_overrides.pop(get_workflow_service, None)

    with capsys.disabled():
        assert_ratecon_pre_webhook_db_state(
            payload=RATECON_WEBHOOK_PAYLOAD,
            tenant_id=_RATECON_E2E_TENANT_ID,
        )

    with TestClient(app) as client:
        r = client.post(
            "/api/webhook/unipile",
            json=RATECON_WEBHOOK_PAYLOAD,
            headers=_auth_headers(),
        )

    print(f"\n[unipile full stack] HTTP {r.status_code}\n{r.text[:12000]}\n")

    assert r.status_code == 200, r.text[:6000]

    body = r.json()
    execution_id = execution_id_from_webhook_response(body)
    assert execution_id, (
        "Expected workflow JSON to include execution_id (top-level or under data); "
        f"keys={list(body.keys()) if isinstance(body, dict) else type(body)!r}"
    )

    with capsys.disabled():
        wait_with_countdown(
            total_s=_POST_WEBHOOK_FULL_STACK_WAIT_S,
            label="ratecon unipile full stack e2e",
        )

    with capsys.disabled():
        row = assert_ratecon_post_webhook_db_state(
            execution_id=execution_id
        )
    assert row["tenant_id"] == "t3ra"
    assert row["event_type"] == "email_received"