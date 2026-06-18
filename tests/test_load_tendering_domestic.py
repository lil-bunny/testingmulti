"""Tests for Gelita domestic/international delivery routing and skip node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.error_catalog import BusinessError
from app.domain.load_tendering_settings import gelita_domestic_delivery_settings
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusType
from app.workflows.graph.routers import domestic_delivery_router, post_read_tender_router
from app.workflows.nodes.gelita.complete_international_tender import (
    complete_international_tender,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _domestic_cfg():
    settings = gelita_domestic_delivery_settings(
        {"tenant_settings": load_tenant_settings_dev("gelita")}
    )
    assert settings is not None
    return settings


@pytest.mark.parametrize(
    ("country", "domestic", "international"),
    [
        ("U.S.A.", True, False),
        ("Canada", True, False),
        ("Mexico", True, False),
        ("Germany", False, True),
        ("Australia", False, True),
        (None, True, False),
        ("", True, False),
        ("Unknown Country", True, False),
    ],
)
def test_delivery_country_classification_from_tenant_config(
    country: str | None, domestic: bool, international: bool
) -> None:
    cfg = _domestic_cfg()
    assert cfg.is_domestic_delivery_country(country) is domestic
    assert cfg.is_international_delivery_country(country) is international


def test_domestic_delivery_router_reads_flag_only() -> None:
    state = SimpleNamespace(data={"is_domestic_delivery": True})
    assert domestic_delivery_router(state) == "domestic"

    state.data["is_domestic_delivery"] = False
    assert domestic_delivery_router(state) == "international"


def test_post_read_tender_router_delegates_by_event_type() -> None:
    state = SimpleNamespace(
        data={"event_type": "tender_created", "is_domestic_delivery": False},
    )
    assert post_read_tender_router(state) == "international"

    state.data["is_domestic_delivery"] = True
    assert post_read_tender_router(state) == "domestic"

    state.data = {
        "event_type": "reminder_due",
        "workflow_lifecycle_status": "processing",
        "tender": {"delivery_date": "2026-06-20"},
    }
    assert post_read_tender_router(state) == "reminder_due"


def _complete_international_state() -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "tender_id": "tender-1",
            "workflow_lifecycle_id": "wl-1",
            "event_type": "tender_created",
        },
    )


@patch("app.workflows.nodes.gelita.complete_international_tender.LifecycleTransitionService")
@patch("app.workflows.nodes.gelita.complete_international_tender.ActivityLogService")
def test_complete_international_tender_logs_exception_and_completes(
    mock_activity_cls: MagicMock,
    mock_lifecycle_cls: MagicMock,
) -> None:
    activity_service = MagicMock()
    mock_activity_cls.return_value = activity_service
    lifecycle_service = MagicMock()
    mock_lifecycle_cls.return_value = lifecycle_service

    complete_international_tender(_complete_international_state())

    activity_service.record_exception.assert_called_once()
    exception_write = activity_service.record_exception.call_args.args[0]
    assert (
        exception_write.description
        == BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.description
    )
    assert exception_write.metadata is not None
    assert (
        exception_write.metadata["error"]
        == BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.value
    )

    lifecycle_service.apply_from_state.assert_called_once()
    kwargs = lifecycle_service.apply_from_state.call_args.kwargs
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE
    assert kwargs["to_status"] == StatusType.COMPLETED
    assert kwargs.get("to_sub_status") is None
