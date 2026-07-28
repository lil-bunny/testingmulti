"""Tests for AscendWriteService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.appointment_scheduling.ascend_write_service import (
    AscendWriteService,
)
from app.services.ascend_oauth_service import AscendOAuthService

_REF = "DIAMOND-RPN00008809"
_ISO = "2026-07-18T10:30:00"

_ASCEND_SHIPMENT = {
    "shipmentStops": [
        {"id": "stop-1", "stopNumber": "1"},
        {"id": "stop-2", "stopNumber": "2"},
    ]
}


def _oauth_token_patch(token: str | None = "token"):
    return patch.object(AscendOAuthService, "get_access_token", return_value=token)


def test_skip_ascend_writes_dry_run_records_activity_from_state() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    activity = MagicMock()
    svc = AscendWriteService(activity_service=activity)
    state = SimpleNamespace(
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        execution_id="22222222-3333-4444-5555-666666666666",
        data={
            "tenant_slug": "t3ra",
            "tenant_settings": {"appointment_scheduling": {"skip_ascend_writes": True}},
            "reference_number": _REF,
            "customer_reply_extraction": {"appointment_start_iso": _ISO},
            "ascend_shipment": _ASCEND_SHIPMENT,
        },
    )
    with _oauth_token_patch() as token_mock:
        result = svc.apply_dropoff_from_state(state)

    token_mock.assert_not_called()
    assert result.ok is True
    assert state.data["ascend_update_result"]["dry_run"] is True
    activity.record_ascend_update.assert_called_once_with(state)


def test_skip_ascend_writes_dry_run_no_http() -> None:
    svc = AscendWriteService()
    with _oauth_token_patch() as token_mock:
        result = svc.apply_dropoff(
            tenant_slug="t3ra",
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": True}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
            ascend_shipment=_ASCEND_SHIPMENT,
        )

    token_mock.assert_not_called()
    assert result.ok is True
    assert result.skipped is True
    assert result.dry_run is True
    assert result.payload is not None
    assert result.payload["shipmentStops"][0]["id"] == "stop-2"


def test_dry_run_refetches_when_ascend_shipment_missing() -> None:
    svc = AscendWriteService()
    with (
        _oauth_token_patch(),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.fetched_shipment_details",
            return_value=_ASCEND_SHIPMENT,
        ) as fetch_mock,
    ):
        result = svc.apply_dropoff(
            tenant_slug="t3ra",
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": True}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )

    fetch_mock.assert_called_once()
    assert result.ok is True
    assert result.dry_run is True


def test_dry_run_fails_when_dropoff_stop_missing_after_refetch() -> None:
    svc = AscendWriteService()
    with (
        _oauth_token_patch(),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.fetched_shipment_details",
            return_value={"shipmentStops": []},
        ),
    ):
        result = svc.apply_dropoff(
            tenant_slug="t3ra",
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": True}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )
    assert result.ok is False
    assert result.failure is not None
    assert result.failure.code == "ascend_invalid_payload"
    assert result.dry_run is False


def test_live_ascend_put_when_writes_enabled() -> None:
    svc = AscendWriteService()
    shipment = {
        "shipmentStops": [
            {"id": "stop-1", "stopNumber": "1"},
            {"id": "stop-2", "stopNumber": "2"},
        ]
    }
    with (
        patch(
            "app.services.appointment_scheduling.ascend_write_service.skip_ascend_writes_enabled",
            return_value=False,
        ),
        _oauth_token_patch(),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.fetched_shipment_details",
            return_value=shipment,
        ),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.update_shipment_stops",
            return_value={"ok": True},
        ) as put_mock,
    ):
        result = svc.apply_dropoff(
            tenant_slug="t3ra",
            tenant_settings={
                "appointment_scheduling": {
                    "skip_ascend_writes": False,
                }
            },
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )

    assert result.ok is True
    assert result.skipped is False
    put_mock.assert_called_once()
    assert put_mock.call_args.kwargs["payload"]["shipmentStops"][0]["id"] == "stop-2"


def test_missing_credentials_when_writes_enabled() -> None:
    svc = AscendWriteService()
    with (
        patch(
            "app.services.appointment_scheduling.ascend_write_service.skip_ascend_writes_enabled",
            return_value=False,
        ),
        _oauth_token_patch(token=None),
    ):
        result = svc.apply_dropoff(
            tenant_slug="t3ra",
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": False}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )
    assert result.ok is False
    assert result.failure is not None
    assert result.failure.code == "ascend_not_configured"
