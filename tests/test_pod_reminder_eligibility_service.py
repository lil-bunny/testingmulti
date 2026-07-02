"""Unit tests for PodLifecycleReminderEligibilityService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.models.status import StatusSubType, StatusType
from app.services.pod_lifecycle.reminder_eligibility_service import (
    PodLifecycleReminderEligibilityService,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def _state_data(*, tenant_settings: dict | None = None) -> dict:
    return {
        "tenant_settings": tenant_settings if tenant_settings is not None else minimal_t3ra_tenant_settings(),
    }


def test_check_skips_when_sub_status_in_tenant_skip_list() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["pod_lifecycle"]["reminders"]["skip_sub_statuses"] = ["document_processed"]
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DOCUMENT_PROCESSED.value,
    }
    svc = PodLifecycleReminderEligibilityService(lifecycle_service=lifecycle)

    result = svc.check(
        workflow_lifecycle_id="wl-1",
        state_data=_state_data(tenant_settings=settings),
    )

    assert not result.eligible
    assert result.skip_reason == f"skip_sub_status_{StatusSubType.DOCUMENT_PROCESSED.value}"


def test_check_eligible_when_sub_status_not_in_skip_list() -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    svc = PodLifecycleReminderEligibilityService(lifecycle_service=lifecycle)

    result = svc.check(
        workflow_lifecycle_id="wl-1",
        state_data=_state_data(),
    )

    assert result.eligible
    assert result.skip_reason is None


def test_check_eligible_when_skip_sub_statuses_empty() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["pod_lifecycle"]["reminders"]["skip_sub_statuses"] = []
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DOCUMENT_PROCESSED.value,
    }
    svc = PodLifecycleReminderEligibilityService(lifecycle_service=lifecycle)

    result = svc.check(
        workflow_lifecycle_id="wl-1",
        state_data=_state_data(tenant_settings=settings),
    )

    assert result.eligible


def test_check_missing_lifecycle_id() -> None:
    svc = PodLifecycleReminderEligibilityService(lifecycle_service=MagicMock())

    result = svc.check(workflow_lifecycle_id=None, state_data=_state_data())

    assert not result.eligible
    assert result.skip_reason == "missing_workflow_lifecycle_id"
