"""Opt-in E2E: ``pod_lifecycle`` ``email_received`` without SMTP or Unipile.

**What this exercises**

1. Queue ``run_workflow_async`` with ``event_type=email_received`` (same Celery entry as production
   after webhook classification — no HTTP webhook).
2. Real ``PodLifecycleIngressService.prepare_email_received_payload`` + ``PodAttachmentIngressGateService``.
3. Real LangGraph ``pod_lifecycle`` with live LLM; fixture bytes via worker env stubs.

**Prerequisites (staging/dev DB)**

- Completed **ratecon** lifecycle (``DOCUMENT_PROCESSED``) for the shipment.
- ``document_analysis`` row with ``ratecon_extraction`` + ``results.extracted_fields``.
- Turvo shipment in allowed POD status (``2116`` / ``2106`` / ``2105``).
- No existing POD ``documents`` or POD analysis rows for ``POD_E2E_SHIPMENTS_ROW_ID``.
- ``pod_lifecycle.shadow_mode: true`` in tenant settings (skips Turvo upload + outbound email).
- **Celery worker + Redis** with the same stub env vars as pytest.

**Run (single PDF)**

::

    set POD_EMAIL_FULL_STACK_E2E=1
    set POD_E2E_STUB_ATTACHMENTS=1
    set POD_E2E_STUB_S3=1
    set POD_E2E_SHIPMENTS_ROW_ID=<shipments.id uuid>
    set POD_E2E_SHIPMENT_ID=<turvo_shipment_id>
    set POD_E2E_THREAD_ID=<unipile_thread_id>
    set POD_E2E_RATECON_LC_ID=<completed_ratecon_lifecycle_uuid>
    set POD_E2E_ATTACHMENT_FIXTURE_PATH=tests/fixtures/testpod.pdf
    uv run celery -A tests.e2e.celery_app_e2e:celery_app worker --loglevel=info --pool=solo
    uv run pytest tests/e2e/scenarios/test_pod_lifecycle_email_catch_up_workflow.py -v -s

**Run (two images — merge path)**

::

    set POD_E2E_ATTACHMENT_FIXTURES={"att-img-1":"tests/fixtures/img1.png","att-img-2":"tests/fixtures/img2.png"}
    rem (unset POD_E2E_ATTACHMENT_FIXTURE_PATH when using FIXTURES map)
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

from app.domain.tenant_settings.registry import parse_tenant_settings
from app.domain.tenant_settings.workflow_shadow_mode import workflow_shadow_mode_enabled
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_lifecycle_ingress_service import PodLifecycleIngressService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService
from tests.e2e.fixtures.pod_email_e2e import (
    build_pod_email_received_payload,
    pod_email_e2e_correlation,
)
from tests.e2e.helpers.db_snapshots import (
    count_workflow_runs_for_shipment,
    fetch_document_analysis_for_shipment,
    fetch_documents_for_shipment,
    fetch_lifecycle_by_id,
)
from tests.e2e.helpers.workflow_runs_db import poll_until_pod_processed

_POD_EVENT = WorkflowRunEventType.EMAIL_RECEIVED.value
_RUN_WORKFLOW_TASK = "app.tasks.workflows.run_workflow_async"
_POLL_DEFAULT_TIMEOUT_S = 180.0
_POLL_DEFAULT_INTERVAL_S = 5.0

_POD_DOCUMENT_ANALYSIS_TYPES = frozenset(
    (
        DocumentAnalysisType.POD_EXTRACTION.value,
        DocumentAnalysisType.POD_VS_RATECON_COMPARISON.value,
    )
)

pytestmark = [pytest.mark.e2e, pytest.mark.pod_lifecycle_email_catch_up_workflow]


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _integration_skip(msg: str) -> None:
    pytest.skip(msg)


def _require_correlation() -> dict[str, str]:
    correlation = pod_email_e2e_correlation()
    if correlation is None:
        _integration_skip(
            "Set POD_E2E_SHIPMENTS_ROW_ID, POD_E2E_SHIPMENT_ID, POD_E2E_THREAD_ID, and "
            "POD_E2E_RATECON_LC_ID (see module docstring)."
        )
    return correlation


def _assert_worker_stub_env() -> None:
    if not _truthy_env("POD_E2E_STUB_ATTACHMENTS") or not _truthy_env("POD_E2E_STUB_S3"):
        _integration_skip(
            "Set POD_E2E_STUB_ATTACHMENTS=1 and POD_E2E_STUB_S3=1 in this shell and start "
            "the Celery worker via tests.e2e.celery_app_e2e with the same vars "
            "(see module docstring)."
        )


def _assert_tenant_settings(correlation: dict[str, str]) -> None:
    from app.repositories.tenants_db_repository import TenantsDbRepository
    from app.core.db import db_scope

    tenant_slug = correlation["tenant_slug"]
    with db_scope() as repos:
        row = TenantsDbRepository(repos.session).get_by_slug(tenant_slug)
    settings = (row or {}).get("settings") or {}
    try:
        parse_tenant_settings(tenant_slug, settings)
    except Exception as exc:
        pytest.fail(
            f"tenants.settings for {tenant_slug!r} failed validation ({exc}). "
            "Fix tenant settings before running this E2E."
        )
    if not workflow_shadow_mode_enabled(settings, workflow_name="pod_lifecycle"):
        pytest.fail(
            "Prerequisite: set pod_lifecycle.shadow_mode: true in tenant settings to skip "
            "Turvo upload and outbound email during E2E."
        )


def _assert_ratecon_prerequisites(correlation: dict[str, str]) -> None:
    _assert_tenant_settings(correlation)
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


def _assert_no_pod_documents(*, docs: list[dict], shipments_row_id: str) -> None:
    pod_rows = [
        d
        for d in docs
        if str(d.get("type") or "").strip() == DocumentType.POD.value
    ]
    if not pod_rows:
        return
    pytest.fail(
        "E2E precondition failed: `documents` already contains POD row(s). Remove them first.\n"
        f"  shipments_row_id={shipments_row_id!r}\n"
        f"  document ids={[d.get('id') for d in pod_rows]!r}"
    )


def _assert_no_pod_analysis(*, analysis: list[dict], shipments_row_id: str) -> None:
    offending = [
        r
        for r in analysis
        if str(r.get("analysis_type") or "").strip() in _POD_DOCUMENT_ANALYSIS_TYPES
    ]
    if not offending:
        return
    pytest.fail(
        "E2E precondition failed: `document_analysis` already has POD analysis rows.\n"
        f"  shipments_row_id={shipments_row_id!r}\n"
        f"  types={[r.get('analysis_type') for r in offending]!r}"
    )


def _assert_ratecon_extraction_cache(*, analysis: list[dict], shipments_row_id: str) -> None:
    rows = [
        r
        for r in analysis
        if str(r.get("analysis_type") or "").strip()
        == DocumentAnalysisType.RATECON_EXTRACTION.value
    ]
    with_fields = [
        r
        for r in rows
        if isinstance(r.get("results"), dict)
        and (r.get("results") or {}).get("extracted_fields")
    ]
    if with_fields:
        return
    pytest.fail(
        "Prerequisite: ratecon_extraction with results.extracted_fields required.\n"
        f"  shipments_row_id={shipments_row_id!r}\n"
        f"  ratecon_extraction rows={len(rows)} with_extracted_fields={len(with_fields)}"
    )


def _assert_not_duplicate_pod_ingest(correlation: dict[str, str]) -> None:
    ingress = PodLifecycleIngressService()
    from app.repositories.tenants_db_repository import find_tenant_uuid_by_slug

    tenant_uuid = find_tenant_uuid_by_slug(correlation["tenant_slug"]) or correlation["tenant_slug"]
    if ingress.is_duplicate_email_pod_ingest(
        tenant_id=tenant_uuid,
        payload={
            "thread_id": correlation["thread_id"],
            "shipment_id": correlation["shipment_id"],
            "shipments_row_id": correlation["shipments_row_id"],
        },
    ):
        _integration_skip(
            "POD lifecycle already at document_processed for this shipment (duplicate gate). "
            "Use a fresh shipment or clear POD lifecycle state."
        )


@pytest.mark.integration
def test_pod_lifecycle_email_received_catch_up_full_stack() -> None:
    """Real gate + LangGraph via Celery; fixture attachments; poll DB for POD outcomes."""
    if not _truthy_env("POD_EMAIL_FULL_STACK_E2E"):
        _integration_skip("Set POD_EMAIL_FULL_STACK_E2E=1 (see module docstring).")

    _assert_worker_stub_env()
    correlation = _require_correlation()
    _assert_ratecon_prerequisites(correlation)
    _assert_not_duplicate_pod_ingest(correlation)

    shipments_row_id = correlation["shipments_row_id"]
    tenant_slug = correlation["tenant_slug"]

    before_docs = fetch_documents_for_shipment(shipment_id=shipments_row_id)
    before_keys = {d["storage_key"] for d in before_docs}
    before_analysis = fetch_document_analysis_for_shipment(shipment_id=shipments_row_id)
    before_analysis_ids = {row["id"] for row in before_analysis}
    before_run_count = count_workflow_runs_for_shipment(
        tenant_id=tenant_slug,
        shipment_id=shipments_row_id,
    )

    _assert_no_pod_documents(docs=before_docs, shipments_row_id=shipments_row_id)
    _assert_no_pod_analysis(analysis=before_analysis, shipments_row_id=shipments_row_id)
    _assert_ratecon_extraction_cache(
        analysis=before_analysis, shipments_row_id=shipments_row_id
    )

    execution_id = str(uuid.uuid4())
    payload = build_pod_email_received_payload(correlation, execution_id=execution_id)

    print(
        "\n[pod email e2e] enqueue email_received",
        f"execution_id={execution_id}",
        f"shipments_row_id={shipments_row_id}",
        f"shipment_id={correlation['shipment_id']}",
        f"attachments={[a.get('id') for a in payload.get('attachments') or []]}\n",
    )

    from app.celery_app import celery_app

    celery_app.send_task(
        _RUN_WORKFLOW_TASK,
        kwargs={
            "tenant_slug": tenant_slug,
            "workflow_name": "pod_lifecycle",
            "payload": payload,
        },
    )

    poll = poll_until_pod_processed(
        execution_id=execution_id,
        shipments_row_id=shipments_row_id,
        before_doc_keys=before_keys,
        before_analysis_ids=before_analysis_ids,
        timeout_s=_float_env("POD_E2E_POLL_TIMEOUT_S", _POLL_DEFAULT_TIMEOUT_S),
        interval_s=_float_env("POD_E2E_POLL_INTERVAL_S", _POLL_DEFAULT_INTERVAL_S),
    )

    assert poll.workflow_run is not None, (
        f"No workflow_runs row for execution_id={execution_id!r} after poll. "
        "Ensure Celery worker is running with POD_E2E_STUB_ATTACHMENTS=1 and POD_E2E_STUB_S3=1."
    )
    assert poll.workflow_run.get("event_type") == _POD_EVENT, poll.workflow_run

    assert poll.new_pod_documents or poll.new_pod_extraction_rows, (
        f"POD processing did not complete within poll window for execution_id={execution_id!r}. "
        "Check worker logs for gate skip (invalid_attachment) or LLM failures. "
        f"last_new_docs={len(poll.new_pod_documents)} "
        f"last_extractions={len(poll.new_pod_extraction_rows)}"
    )

    after_run_count = count_workflow_runs_for_shipment(
        tenant_id=tenant_slug,
        shipment_id=shipments_row_id,
    )
    assert after_run_count == before_run_count + 1, (
        f"workflow_runs count expected {before_run_count + 1}, got {after_run_count}"
    )

    wl_id = str(poll.workflow_run.get("workflow_lifecycle_id") or "").strip()
    assert wl_id
    lc = fetch_lifecycle_by_id(lifecycle_id=wl_id)
    assert lc is not None
    assert lc.get("workflow_name") == "pod_lifecycle"

    for doc in poll.new_pod_documents:
        assert doc["shipment_id"] == shipments_row_id
        assert "pod_attachments" in str(doc.get("storage_key") or "")

    new_ratecon = [
        r
        for r in fetch_document_analysis_for_shipment(shipment_id=shipments_row_id)
        if str(r.get("analysis_type") or "").strip()
        == DocumentAnalysisType.RATECON_EXTRACTION.value
        and r.get("id") not in before_analysis_ids
    ]
    assert not new_ratecon, "pod_lifecycle must not create new ratecon_extraction rows"

    for row in poll.new_pod_extraction_rows:
        assert isinstance(row.get("results"), dict)

    print(
        "\n[pod email e2e] OK",
        f"execution_id={execution_id}",
        f"new_pod_docs={len(poll.new_pod_documents)}",
        f"new_pod_extractions={len(poll.new_pod_extraction_rows)}\n",
    )
