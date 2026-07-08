"""Unit tests for POD lifecycle duplicate-email guard."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.pod_lifecycle.guards import (
    is_pod_processing_complete_sub_status,
    pod_reminder_skip_sub_statuses,
)
from app.models.status import StatusSubType
from app.services.pod_lifecycle.ingress_service import PodLifecycleIngressService


def test_is_pod_processing_complete_sub_status():
    assert is_pod_processing_complete_sub_status(StatusSubType.DOCUMENT_PROCESSED)
    assert is_pod_processing_complete_sub_status(StatusSubType.UPLOADED_TO_TMS)
    assert is_pod_processing_complete_sub_status(StatusSubType.RESOLVED_MANUALLY)
    assert not is_pod_processing_complete_sub_status(StatusSubType.DOCUMENT_UPLOADED)
    assert not is_pod_processing_complete_sub_status(None)


def test_pod_reminder_skip_sub_statuses_includes_document_processed():
    assert StatusSubType.DOCUMENT_PROCESSED.value in pod_reminder_skip_sub_statuses()


def test_is_duplicate_email_pod_ingest_when_processing_complete():
    ingress = PodLifecycleIngressService(
        lifecycle_service=MagicMock(
            read_lifecycle_row_by_id=MagicMock(
                return_value={"sub_status": StatusSubType.DOCUMENT_PROCESSED.value}
            )
        ),
    )
    ingress._resolve_email_pod_lifecycle_id = MagicMock(return_value="wl-1")  # type: ignore[method-assign]

    assert ingress.is_duplicate_email_pod_ingest(
        tenant_id="tenant-uuid",
        payload={"thread_id": "thr-1"},
    )


def test_is_duplicate_email_pod_ingest_false_without_lifecycle():
    ingress = PodLifecycleIngressService()
    ingress._resolve_email_pod_lifecycle_id = MagicMock(return_value=None)  # type: ignore[method-assign]

    assert not ingress.is_duplicate_email_pod_ingest(
        tenant_id="tenant-uuid",
        payload={"thread_id": "thr-1"},
    )
