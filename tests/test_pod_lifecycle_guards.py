"""Unit tests for POD lifecycle guard helpers."""

from __future__ import annotations

import pytest

from app.domain.pod_lifecycle_guards import (
    POD_EMAIL_ALLOWED_TURVO_STATUS_KEYS,
    POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,
    POD_UPLOAD_ACTIVITY_DONE_SUB_STATUSES,
    is_manual_fresh_pod_upload,
    is_manual_pod_upload,
    pod_email_status_eligible_from_turvo_payload,
    should_skip_idempotent_pod_activity_log,
)
from app.models.status import StatusSubType


def test_is_manual_pod_upload_true():
    assert is_manual_pod_upload({"event_type": "manual_pod_upload"}) is True


def test_is_manual_pod_upload_false_for_email():
    assert is_manual_pod_upload({"event_type": "email_received"}) is False


def test_is_manual_fresh_pod_upload_true_for_upload_source():
    data = {
        "event_type": "manual_pod_upload",
        "manual_pod_upload_source": "upload",
    }
    assert is_manual_fresh_pod_upload(data) is True


def test_is_manual_fresh_pod_upload_false_for_stored():
    data = {
        "event_type": "manual_pod_upload",
        "manual_pod_upload_source": "stored",
    }
    assert is_manual_fresh_pod_upload(data) is False


def test_is_manual_fresh_pod_upload_false_for_email():
    data = {"event_type": "email_received"}
    assert is_manual_fresh_pod_upload(data) is False


def test_should_skip_idempotent_pod_activity_log_email_when_uploaded():
    data = {"event_type": "email_received"}
    row = {"sub_status": StatusSubType.DOCUMENT_UPLOADED.value}
    assert (
        should_skip_idempotent_pod_activity_log(
            data,
            row,
            done_sub_statuses=POD_UPLOAD_ACTIVITY_DONE_SUB_STATUSES,
        )
        is True
    )


def test_should_skip_idempotent_pod_activity_log_manual_fresh_never_skips():
    data = {
        "event_type": "manual_pod_upload",
        "manual_pod_upload_source": "upload",
    }
    row = {"sub_status": StatusSubType.DOCUMENT_PROCESSED.value}
    assert (
        should_skip_idempotent_pod_activity_log(
            data,
            row,
            done_sub_statuses=POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,
        )
        is False
    )


def test_should_skip_idempotent_pod_activity_log_manual_stored_skips_when_processed():
    data = {
        "event_type": "manual_pod_upload",
        "manual_pod_upload_source": "stored",
    }
    row = {"sub_status": StatusSubType.DOCUMENT_PROCESSED.value}
    assert (
        should_skip_idempotent_pod_activity_log(
            data,
            row,
            done_sub_statuses=POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,
        )
        is True
    )


@pytest.mark.parametrize("status_key", sorted(POD_EMAIL_ALLOWED_TURVO_STATUS_KEYS))
def test_pod_email_status_eligible_allowed_keys(status_key: str) -> None:
    shipment = {"details": {"status": {"code": {"key": status_key}}}}
    assert pod_email_status_eligible_from_turvo_payload(shipment) is True


def test_pod_email_status_eligible_covered_false() -> None:
    shipment = {"details": {"status": {"code": {"key": "2102"}}}}
    assert pod_email_status_eligible_from_turvo_payload(shipment) is False
