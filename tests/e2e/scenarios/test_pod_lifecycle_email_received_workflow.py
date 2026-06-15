from __future__ import annotations

import copy

import pytest

from app.core.config import settings
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.repositories.tenants_db_repository import find_tenant_uuid_by_slug
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService
from tests.e2e.clients import post_json
from tests.e2e.config import E2E_API_BASE_URL, E2E_POD_LIFECYCLE_SHIPMENT_ID, pod_email_e2e_ready
from tests.e2e.helpers.db_snapshots import (
    count_workflow_runs_for_shipment,
    fetch_document_analysis_for_shipment,
    fetch_documents_for_shipment,
    fetch_lifecycle_by_id,
    fetch_ratecon_lifecycle_for_thread,
)
from tests.e2e.helpers.countdown_wait import wait_with_countdown
from tests.e2e.helpers.http_error_reporting import format_unipile_webhook_failure
from tests.e2e.helpers.snapshot_reporting import (
    emit_db_snapshot_report,
    format_analysis_lines,
    format_doc_lines,
)
from tests.e2e.helpers.workflow_runs_db import execution_id_from_webhook_response


def _graph_tenant_row_uuid(graph_key: str) -> str:
    u = find_tenant_uuid_by_slug(graph_key.strip())
    return u if u else graph_key.strip()


pytestmark = [pytest.mark.e2e, pytest.mark.pod_lifecycle_email_workflow]

# Fire-and-forget webhook: allow Celery + graph time before before/after DB comparison.
_POST_WEBHOOK_WAIT_S = 240


_POD_DOCUMENT_ANALYSIS_TYPES = frozenset(
    (
        DocumentAnalysisType.POD_EXTRACTION.value,
        DocumentAnalysisType.POD_VS_RATECON_COMPARISON.value,
    )
)


def _assert_no_pod_documents_before_e2e(
    *, before_docs: list[dict], shipment_id: str
) -> None:
    """Ratecon (or empty) is fine; existing POD rows must be removed first."""
    pod_rows = [
        d
        for d in before_docs
        if str(d.get("type") or "").strip() == DocumentType.POD.value
    ]
    if not pod_rows:
        return
    keys = [d.get("storage_key") for d in pod_rows]
    ids = [d.get("id") for d in pod_rows]
    pytest.fail(
        "E2E precondition failed: `documents` already contains `pod` row(s) for this "
        f"shipment_id. Remove them first, then re-run.\n"
        f"  shipment_id={shipment_id!r}\n"
        f"  document ids={ids!r}\n"
        f"  storage_keys={keys!r}\n"
        "  (Only `ratecon` rows, or no rows, are allowed before this test.)"
    )


def _assert_no_pod_document_analysis_before_e2e(
    *, before_analysis: list[dict], shipment_id: str
) -> None:
    """Fail if POD analysis rows already exist; ratecon_extraction from ratecon workflow is allowed."""
    offending = [
        r
        for r in before_analysis
        if str(r.get("analysis_type") or "").strip() in _POD_DOCUMENT_ANALYSIS_TYPES
    ]
    if not offending:
        return
    types_hit = sorted({str(r.get("analysis_type")) for r in offending})
    ids = [r.get("id") for r in offending]
    pytest.fail(
        "E2E precondition failed: `document_analysis` already has POD analysis row(s) for this "
        "shipment. Remove pod_extraction / pod_vs_ratecon_comparison rows or pick another "
        f"shipment_id, then re-run.\n"
        f"  shipment_id={shipment_id!r}\n"
        f"  analysis_types_found={types_hit!r}\n"
        f"  row ids={ids!r}"
    )


def _assert_ratecon_extraction_before_e2e(
    *, before_analysis: list[dict], shipment_id: str
) -> None:
    """Pod lifecycle loads cached ratecon extraction; ratecon workflow must have run first."""
    rows = [
        r
        for r in before_analysis
        if str(r.get("analysis_type") or "").strip()
        == DocumentAnalysisType.RATECON_EXTRACTION.value
    ]
    with_extracted_fields = [
        r
        for r in rows
        if isinstance(r.get("results"), dict)
        and (r.get("results") or {}).get("extracted_fields")
    ]
    if with_extracted_fields:
        return
    pytest.fail(
        "Prerequisite: `ratecon_extraction` row with `results.extracted_fields` required "
        "in `document_analysis` before POD reply e2e (pod lifecycle no longer re-runs ratecon LLM).\n"
        f"  shipment_id={shipment_id!r}\n"
        f"  ratecon_extraction rows found={len(rows)} with_extracted_fields={len(with_extracted_fields)}"
    )


@pytest.mark.order(3)
def test_pod_lifecycle_email_received_unipile_webhook(
    pod_reply_fixture_payload: dict,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """POST returns only ``execution_id``; we wait 4m (live countdown) then compare DB before/after."""
    ok, reason = pod_email_e2e_ready()
    if not ok:
        pytest.skip(reason)

    shipment_id = E2E_POD_LIFECYCLE_SHIPMENT_ID.strip()
    base_url = E2E_API_BASE_URL.strip()

    thread_id = str(pod_reply_fixture_payload.get("thread_id") or "").strip()
    assert thread_id, "fixture pod_reply_webhook_payload.json must include a non-empty thread_id"

    tenant_id = "t3ra"
    ratecon_lc = fetch_ratecon_lifecycle_for_thread(tenant_id=tenant_id, thread_id=thread_id)
    if not ratecon_lc:
        pytest.fail(
            "Prerequisite: no ratecon lifecycle linked to this thread via communications → "
            "workflow_runs.\n"
            f"  thread_id={thread_id!r}\n"
            "  Seed or run ratecon for this thread before the POD reply e2e."
        )

    WorkflowLifecycleService().resolve_or_create_lifecycle(
        tenant_id=tenant_id,
        workflow_name="pod_lifecycle",
        payload={
            "thread_id": thread_id,
            "shipment_id": shipment_id,
        },
    )

    payload = copy.deepcopy(pod_reply_fixture_payload)
    payload["shipment_id"] = shipment_id
    subj = str(payload.get("subject") or "")
    if "rate confirmation" not in subj.lower():
        payload["subject"] = (subj + " rate confirmation").strip()

    secret = settings.UNIPILE_WEBHOOK_SECRET
    assert secret

    before_docs = fetch_documents_for_shipment(shipment_id=shipment_id)
    before_keys = {d["storage_key"] for d in before_docs}
    before_analysis = fetch_document_analysis_for_shipment(shipment_id=shipment_id)
    before_analysis_ids = {row["id"] for row in before_analysis}
    before_run_count = count_workflow_runs_for_shipment(
        tenant_id=tenant_id, shipment_id=shipment_id
    )

    _assert_no_pod_documents_before_e2e(
        before_docs=before_docs, shipment_id=shipment_id
    )
    _assert_no_pod_document_analysis_before_e2e(
        before_analysis=before_analysis, shipment_id=shipment_id
    )
    _assert_ratecon_extraction_before_e2e(
        before_analysis=before_analysis, shipment_id=shipment_id
    )

    before_lines: list[str] = [
        f"  shipment_id={shipment_id!r}",
        f"  thread_id={thread_id!r}",
        f"  prerequisite ratecon lifecycle id={ratecon_lc.get('id')!r}",
        f"  workflow_runs (tenant + shipment_id): {before_run_count}",
    ]
    before_lines.extend(format_doc_lines(before_docs))
    before_lines.extend(format_analysis_lines(before_analysis))
    emit_db_snapshot_report(capsys, "BEFORE snapshot (pre-webhook)", before_lines)

    resp = post_json(
        base_url=base_url,
        path="/api/webhook/unipile",
        json_body=payload,
        headers={"Authorization": f"Bearer {secret}"},
    )
    if resp.status_code != 200:
        pytest.fail(format_unipile_webhook_failure(resp))

    # Use extraction helper for execution_id
    execution_id = execution_id_from_webhook_response(resp)
    assert execution_id, f"missing execution_id in response keys={list(resp.json().keys())}"

    with capsys.disabled():
        wait_with_countdown(
            total_s=_POST_WEBHOOK_WAIT_S,
            label="pod_lifecycle email_received e2e",
        )

    run_row = WorkflowRunsService().fetch_workflow_run_by_id(run_id=str(execution_id))
    assert run_row is not None, (
        f"No workflow_runs row for execution_id={execution_id!r} after "
        f"{_POST_WEBHOOK_WAIT_S}s wait — Celery worker may be down or graph too slow."
    )
    assert run_row.get("event_type") == "email_received"
    assert run_row.get("tenant_id") == _graph_tenant_row_uuid(tenant_id)

    after_run_count = count_workflow_runs_for_shipment(
        tenant_id=tenant_id, shipment_id=shipment_id
    )
    assert after_run_count == before_run_count + 1, (
        "workflow_runs count for (tenant_id, shipment_id) must go from n to n+1 after this run.\n"
        f"  shipment_id={shipment_id!r} tenant_id={tenant_id!r}\n"
        f"  before_count={before_run_count} after_count={after_run_count} "
        f"(expected {before_run_count + 1})"
    )
    wl_id = run_row.get("workflow_lifecycle_id")
    assert wl_id
    lc = fetch_lifecycle_by_id(lifecycle_id=str(wl_id))
    assert lc is not None
    assert lc.get("workflow_name") == "pod_lifecycle"
    assert lc.get("tenant_id") == _graph_tenant_row_uuid(tenant_id)
    assert (lc.get("shipment_id") or "") == shipment_id

    after_docs = fetch_documents_for_shipment(shipment_id=shipment_id)
    new_docs = [d for d in after_docs if d["storage_key"] not in before_keys]

    after_analysis = fetch_document_analysis_for_shipment(shipment_id=shipment_id)
    new_analysis = [r for r in after_analysis if r["id"] not in before_analysis_ids]

    after_lines: list[str] = [
        f"  shipment_id={shipment_id!r}",
        f"  execution_id={execution_id!r}",
        f"  workflow_runs (tenant + shipment_id): {after_run_count} (before was {before_run_count})",
        f"  documents: total={len(after_docs)} new_since_before={len(new_docs)}",
    ]
    after_lines.extend(format_doc_lines(new_docs, max_rows=12))
    after_lines.append(
        f"  document_analysis: total={len(after_analysis)} new_since_before={len(new_analysis)}"
    )
    after_lines.extend(format_analysis_lines(new_analysis, max_rows=12))
    emit_db_snapshot_report(capsys, "AFTER snapshot (post-webhook)", after_lines)

    for d in new_docs:
        assert d["shipment_id"] == shipment_id
        assert "pod_attachments" in d["storage_key"], (
            f"storage_key unexpected: {d['storage_key']}"
        )

    new_ratecon_rows = [
        r
        for r in new_analysis
        if str(r.get("analysis_type") or "").strip()
        == DocumentAnalysisType.RATECON_EXTRACTION.value
    ]
    assert not new_ratecon_rows, (
        "pod_lifecycle must not re-run ratecon extraction; "
        f"unexpected new ratecon_extraction rows: {new_ratecon_rows!r}"
    )

    for row in new_analysis:
        if row.get("analysis_type") == "pod_extraction" and row.get("results") is not None:
            assert isinstance(row["results"], dict)

    pod_rows = [r for r in after_analysis if r.get("analysis_type") == "pod_extraction"]
    if pod_rows:
        assert isinstance(pod_rows[-1].get("results"), dict)

    dup_check = WorkflowRunsService().fetch_workflow_run_by_id(run_id=str(execution_id))
    assert dup_check is not None and dup_check.get("id") == str(execution_id)
