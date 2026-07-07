"""Tests for Gelita domestic/international delivery routing and skip node."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.domain.error_catalog import BusinessError
from app.domain.load_tendering_settings import (
    gelita_domestic_delivery_settings,
    gelita_skipped_pack_codes_settings,
)
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.workflows.graph.routers import domestic_delivery_router, post_read_tender_router
from app.workflows.nodes.gelita.resolve_international_delivery_skip import (
    resolve_international_delivery_skip,
)
from app.workflows.nodes.gelita.resolve_pack_code_skip import (
    resolve_pack_code_skip,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _domestic_cfg():
    settings = gelita_domestic_delivery_settings(
        {"tenant_settings": load_tenant_settings_dev("gelita")}
    )
    assert settings is not None
    return settings


def test_skipped_pack_codes_from_tenant_config() -> None:
    cfg = gelita_skipped_pack_codes_settings(
        {"tenant_settings": load_tenant_settings_dev("gelita")}
    )
    assert cfg.pack_codes == ["3002"]


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
    state.data["skipped_pack_codes"] = []
    state.data["tender"] = {"tender_products": [{"pack_code": "5366"}]}
    assert post_read_tender_router(state) == "domestic"

    state.data["skipped_pack_codes"] = ["3002"]
    state.data["tender"] = {"tender_products": [{"pack_code": "3002"}]}
    assert post_read_tender_router(state) == "pack_code_skipped"

    state.data["skipped_pack_codes"] = []
    state.data["tender"] = {"tender_products": [{"pack_code": "3002"}]}
    assert post_read_tender_router(state) == "domestic"

    state.data = {
        "event_type": "reminder_due",
        "workflow_lifecycle_status": "processing",
        "tender": {"delivery_date": "2026-06-20"},
    }
    assert post_read_tender_router(state) == "reminder_due"

    state.data = {"event_type": "ack_received", "routing_guide_failover": True}
    assert post_read_tender_router(state) == "routing_guide_failover"


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


@patch(
    "app.workflows.nodes.gelita.resolve_international_delivery_skip.LifecycleTransitionService"
)
@patch("app.workflows.nodes.gelita.resolve_international_delivery_skip.ActivityLogService")
def test_resolve_international_delivery_skip_logs_info_and_completes(
    mock_activity_cls: MagicMock,
    mock_lifecycle_cls: MagicMock,
) -> None:
    activity_service = MagicMock()
    mock_activity_cls.return_value = activity_service
    lifecycle_service = MagicMock()
    mock_lifecycle_cls.return_value = lifecycle_service

    resolve_international_delivery_skip(_complete_international_state())

    activity_service.record_info.assert_called_once()
    info_write = activity_service.record_info.call_args.args[0]
    assert (
        info_write.description
        == BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.description
    )
    assert info_write.metadata is not None
    assert (
        info_write.metadata["error"]
        == BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.value
    )

    lifecycle_service.apply_from_state.assert_called_once()
    kwargs = lifecycle_service.apply_from_state.call_args.kwargs
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE
    assert kwargs["to_status"] == StatusType.COMPLETED
    assert kwargs["to_sub_status"] == StatusSubType.RESOLVED_MANUALLY
    assert not kwargs.get("metadata")


@patch("app.workflows.nodes.gelita.resolve_pack_code_skip.LifecycleTransitionService")
@patch("app.workflows.nodes.gelita.resolve_pack_code_skip.ActivityLogService")
def test_resolve_pack_code_skip_logs_info_and_completes(
    mock_activity_cls: MagicMock,
    mock_lifecycle_cls: MagicMock,
) -> None:
    activity_service = MagicMock()
    mock_activity_cls.return_value = activity_service
    lifecycle_service = MagicMock()
    mock_lifecycle_cls.return_value = lifecycle_service

    resolve_pack_code_skip(
        WorkflowState(
            tenant_id="tenant-1",
            tenant_slug="gelita",
            execution_id="run-1",
            data={
                "tender_id": "tender-1",
                "workflow_lifecycle_id": "wl-1",
                "event_type": "tender_created",
                "matched_skipped_pack_code": "3002",
            },
        )
    )

    activity_service.record_info.assert_called_once()
    info_write = activity_service.record_info.call_args.args[0]
    assert info_write.description == "Pack code 3002 is skipped"
    assert info_write.metadata is not None
    assert info_write.metadata["error"] == BusinessError.PACK_CODE_SKIPPED.value
    assert info_write.metadata["pack_code"] == "3002"

    lifecycle_service.apply_from_state.assert_called_once()
    kwargs = lifecycle_service.apply_from_state.call_args.kwargs
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE
    assert kwargs["to_status"] == StatusType.COMPLETED
    assert kwargs["to_sub_status"] == StatusSubType.RESOLVED_MANUALLY
    assert not kwargs.get("metadata")
