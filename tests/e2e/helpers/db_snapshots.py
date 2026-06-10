"""Read-only Postgres snapshots for E2E (same ``DATABASE_URL`` as the app)."""

from __future__ import annotations

from typing import Any

from app.core.db import db_scope

from tests.db.e2e import communications_correlation_snapshots as comms_snapshots
from tests.db.e2e import document_analysis_reads, documents_reads
from tests.db.e2e import workflow_lifecycle_snapshots as wl_snapshots
from tests.db.e2e import workflow_runs_reads


def fetch_documents_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    """``shipment_id`` is ``shipments.id`` (UUID), matching ``workflow_lifecycles.shipment_id``."""
    with db_scope() as repos:
        return documents_reads.list_by_shipment(
            repos.session, shipments_row_id=shipment_id
        )


def fetch_document_analysis_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    """``shipment_id`` is ``shipments.id`` (UUID)."""
    with db_scope() as repos:
        return document_analysis_reads.list_by_shipment(
            repos.session, shipments_row_id=shipment_id
        )


def fetch_lifecycle_by_id(*, lifecycle_id: str) -> dict[str, Any] | None:
    with db_scope() as repos:
        return wl_snapshots.read_by_id(repos.session, lifecycle_id=lifecycle_id)


def fetch_ratecon_lifecycle_for_thread(*, tenant_id: str, thread_id: str) -> dict[str, Any] | None:
    """Latest ``ratecon`` lifecycle for this thread via ``communications`` → ``workflow_runs``."""
    with db_scope() as repos:
        return wl_snapshots.find_latest_ratecon_by_thread(
            repos.session,
            tenant_id=tenant_id,
            thread_id=thread_id,
        )


def fetch_lifecycles_for_email_thread(*, tenant_id: str, thread_id: str) -> list[dict[str, Any]]:
    """Lifecycles linked to this Unipile ``thread_id`` via ``communications`` → ``workflow_runs``."""
    with db_scope() as repos:
        return wl_snapshots.list_by_email_thread(
            repos.session,
            tenant_id=tenant_id,
            thread_id=thread_id,
        )


def fetch_load_tendering_lifecycle_for_thread(
    *, tenant_id: str, thread_id: str
) -> dict[str, Any] | None:
    """``load_tendering`` lifecycle resolved via comms ``workflow_run_id`` (Gelita correlation)."""
    with db_scope() as repos:
        return comms_snapshots.find_load_tendering_lifecycle_by_thread(
            repos.session,
            tenant_id=tenant_id,
            thread_id=thread_id,
        )


def fetch_lifecycles_for_tenant_shipment(*, tenant_id: str, shipment_id: str) -> list[dict[str, Any]]:
    """All ``workflow_lifecycles`` rows for this tenant and Turvo ``shipment_id`` (text match)."""
    with db_scope() as repos:
        return wl_snapshots.list_by_tenant_shipment(
            repos.session,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
        )


def count_workflow_runs_for_shipment(*, tenant_id: str, shipment_id: str) -> int:
    """Count workflow_runs executions whose lifecycle ties this tenant UUID and shipment_id."""
    with db_scope() as repos:
        return workflow_runs_reads.count_by_tenant_shipment(
            repos.session,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
        )
