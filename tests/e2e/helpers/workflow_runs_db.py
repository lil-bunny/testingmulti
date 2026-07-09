"""Read-only ``workflow_runs`` queries and execution-id parsing for E2E."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.core.db import db_scope
from app.models.document import DocumentType
from app.models.document_analysis import DocumentAnalysisType
from app.services.workflow_runs_service import WorkflowRunsService

from tests.db.e2e import workflow_runs_reads
from tests.e2e.helpers.db_snapshots import (
    fetch_document_analysis_for_shipment,
    fetch_documents_for_shipment,
)


def fetch_latest_workflow_run_for_tenant_shipment(
    tenant_id: str,
    shipment_id: str,
) -> dict[str, Any] | None:
    """Latest ``workflow_runs`` row tied to lifecycle rows with this shipment (newest ``created_at``)."""
    with db_scope() as repos:
        return workflow_runs_reads.fetch_latest_by_tenant_shipment(
            repos.session,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
        )


def list_workflow_runs_for_lifecycle_event_type(
    workflow_lifecycle_id: str,
    event_type: str,
) -> list[dict[str, Any]]:
    """All matching rows for one lifecycle and ``event_type``, ``created_at`` ascending."""
    with db_scope() as repos:
        rows = workflow_runs_reads.list_by_lifecycle_event_type(
            repos.session,
            workflow_lifecycle_id=workflow_lifecycle_id,
            event_type=event_type,
        )
    return [{**row, "shipment_id": None} for row in rows]


def execution_id_from_webhook_response(body: Any) -> str | None:
    """``execution_id`` from Unipile webhook JSON (top-level or under ``data``)."""
    if not isinstance(body, dict):
        return None
    top = body.get("execution_id")
    if top is not None and str(top).strip():
        return str(top).strip()
    data = body.get("data")
    if isinstance(data, dict):
        nested = data.get("execution_id")
        if nested is not None and str(nested).strip():
            return str(nested).strip()
    return None


@dataclass(frozen=True)
class PodProcessedPollResult:
    workflow_run: dict[str, Any] | None
    new_pod_documents: list[dict[str, Any]]
    new_pod_extraction_rows: list[dict[str, Any]]


def poll_until_pod_processed(
    *,
    execution_id: str,
    shipments_row_id: str,
    before_doc_keys: set[str],
    before_analysis_ids: set[str],
    timeout_s: float = 180.0,
    interval_s: float = 5.0,
) -> PodProcessedPollResult:
    """Poll until ``workflow_runs`` exists and POD document or extraction rows appear."""
    runs = WorkflowRunsService()
    deadline = time.monotonic() + max(timeout_s, 1.0)
    interval_s = max(interval_s, 0.5)
    last_run: dict[str, Any] | None = None
    last_docs: list[dict[str, Any]] = []
    last_extractions: list[dict[str, Any]] = []

    while time.monotonic() < deadline:
        last_run = runs.fetch_workflow_run_by_id(run_id=str(execution_id))
        after_docs = fetch_documents_for_shipment(shipment_id=shipments_row_id)
        last_docs = [
            d
            for d in after_docs
            if str(d.get("type") or "").strip() == DocumentType.POD.value
            and d.get("storage_key") not in before_doc_keys
        ]
        after_analysis = fetch_document_analysis_for_shipment(shipment_id=shipments_row_id)
        last_extractions = [
            r
            for r in after_analysis
            if str(r.get("analysis_type") or "").strip()
            == DocumentAnalysisType.POD_EXTRACTION.value
            and r.get("id") not in before_analysis_ids
            and r.get("results") is not None
        ]
        print(
            "[pod e2e poll]",
            f"execution_id={execution_id}",
            f"run_row={'yes' if last_run else 'no'}",
            f"new_pod_docs={len(last_docs)}",
            f"new_pod_extractions={len(last_extractions)}",
        )
        if last_run is not None and (last_docs or last_extractions):
            return PodProcessedPollResult(
                workflow_run=last_run,
                new_pod_documents=last_docs,
                new_pod_extraction_rows=last_extractions,
            )
        time.sleep(interval_s)

    return PodProcessedPollResult(
        workflow_run=last_run,
        new_pod_documents=last_docs,
        new_pod_extraction_rows=last_extractions,
    )
