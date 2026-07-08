"""Tests for PodLifecycleIngressService route_completed dedupe and email ingress."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pod_lifecycle.ingress_service import (
    POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS,
    POD_EMAIL_SKIP_TURVO_FETCH_FAILED,
    ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
    ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
    PodEmailIngressSkipped,
    PodLifecycleIngressService,
)

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_TURVO_SHIPMENT = "1000324895"


def _mock_ratecon_gate_pass(lifecycle: MagicMock) -> None:
    lifecycle.read_lifecycle.return_value = {
        "found": True,
        "lifecycle_id": "ratecon-lc-1",
    }


def _valid_turvo_shipment(status_key: str = "2116") -> dict:
    return {"details": {"status": {"code": {"key": status_key}}}}


def _patch_valid_turvo_get():
    return patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        return_value=_valid_turvo_shipment(),
    )


def test_check_route_completed_duplicate_not_route_completed_event() -> None:
    svc = PodLifecycleIngressService()
    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "email_received", "shipment_id": _TURVO_SHIPMENT},
    )
    assert result.is_duplicate is False


def test_check_route_completed_duplicate_no_shipments_row() -> None:
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = None
    svc = PodLifecycleIngressService(shipments_service=shipments)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
    )

    assert result.is_duplicate is False
    assert result.lifecycle_id is None


def test_check_route_completed_duplicate_first_time_no_lifecycle() -> None:
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    svc = PodLifecycleIngressService(lifecycle_service=lifecycle)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={
            "event_type": "route_completed",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
        },
    )

    assert result.is_duplicate is False
    assert result.shipments_row_id == _SHIPMENTS_ROW_UUID
    lifecycle.check_lifecycle_exists.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_name="pod_lifecycle",
        shipment_id=_SHIPMENTS_ROW_UUID,
    )


def test_check_route_completed_duplicate_when_prior_run_exists() -> None:
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _LIFECYCLE_UUID,
    }
    runs = MagicMock()
    runs.is_workflow_initial_path_blocked.return_value = True
    svc = PodLifecycleIngressService(lifecycle_service=lifecycle, runs_service=runs)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={
            "event_type": "route_completed",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
        },
    )

    assert result.is_duplicate is True
    assert result.lifecycle_id == _LIFECYCLE_UUID
    runs.is_workflow_initial_path_blocked.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        event_type="route_completed",
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        shipment_id=_SHIPMENTS_ROW_UUID,
        exclude_run_id=None,
    )


def test_check_route_completed_duplicate_resolves_shipments_row_from_turvo_number() -> None:
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_UUID}
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    svc = PodLifecycleIngressService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
    )

    assert result.is_duplicate is False
    shipments.get_by_shipment_number.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_number=_TURVO_SHIPMENT,
    )


@pytest.mark.asyncio
async def test_check_route_completed_convoy_gate_skips_convoy_carrier() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        return_value={
            "details": {"carrierOrder": [{"carrier": {"name": "Convoy Platform"}}]},
        },
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_convoy_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is True
    assert result.reason == ROUTE_COMPLETED_SKIP_CONVOY_LOAD


@pytest.mark.asyncio
async def test_check_route_completed_convoy_gate_proceeds_for_non_convoy() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        return_value={
            "details": {"carrierOrder": [{"carrier": {"name": "Acme Trucking"}}]},
        },
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_convoy_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is False


@pytest.mark.asyncio
async def test_check_route_completed_convoy_gate_fail_open_on_turvo_error() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        side_effect=RuntimeError("turvo down"),
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_convoy_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is False


@pytest.mark.asyncio
async def test_check_route_completed_pod_gate_skips_when_pod_exists() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.check_pod_by_shipment_id",
        new_callable=AsyncMock,
        return_value={"success": True, "pod_exists": True},
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_pod_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is True
    assert result.reason == ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS


@pytest.mark.asyncio
async def test_check_route_completed_pod_gate_proceeds_when_no_pod() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.check_pod_by_shipment_id",
        new_callable=AsyncMock,
        return_value={"success": True, "pod_exists": False},
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_pod_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is False


@pytest.mark.asyncio
async def test_check_route_completed_pod_gate_fail_open_on_turvo_error() -> None:
    with patch(
        "app.services.pod_lifecycle.ingress_service.check_pod_by_shipment_id",
        new_callable=AsyncMock,
        return_value={"success": False, "pod_exists": False},
    ):
        svc = PodLifecycleIngressService()
        result = await svc.check_route_completed_pod_gate(
            tenant_slug="t3ra",
            payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
        )
    assert result.skip is False


@pytest.mark.asyncio
async def test_prepare_email_received_payload_passthrough_when_shipments_row_id_set() -> None:
    comms = MagicMock()
    shipments = MagicMock()
    shipments.get_by_id.return_value = {"shipment_number": _TURVO_SHIPMENT}
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _LIFECYCLE_UUID,
    }
    _mock_ratecon_gate_pass(lifecycle)
    svc = PodLifecycleIngressService(
        communications_service=comms,
        shipments_service=shipments,
        lifecycle_service=lifecycle,
    )

    with _patch_valid_turvo_get():
        out = await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={
                "event_type": "email_received",
                "shipments_row_id": _SHIPMENTS_ROW_UUID,
                "thread_id": "thread-1",
            },
        )

    assert out["shipments_row_id"] == _SHIPMENTS_ROW_UUID
    assert out["shipment_id"] == _TURVO_SHIPMENT
    assert out["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    comms.find_shipment_context_for_thread.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_email_received_payload_resolves_from_thread() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "ratecon-lc-1",
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
        {
            "lifecycle_id": _LIFECYCLE_UUID,
            "workflow_name": "pod_lifecycle",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
    ]
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    _mock_ratecon_gate_pass(lifecycle)
    svc = PodLifecycleIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    with _patch_valid_turvo_get():
        out = await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={
                "event_type": "email_received",
                "thread_id": "thread-abc",
            },
        )

    assert out["shipments_row_id"] == _SHIPMENTS_ROW_UUID
    assert out["shipment_id"] == _TURVO_SHIPMENT
    assert out["workflow_lifecycle_id"] == _LIFECYCLE_UUID
    comms.find_shipment_context_for_thread.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        thread_id="thread-abc",
    )


@pytest.mark.asyncio
async def test_prepare_email_received_payload_thread_without_pod_lc() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "ratecon-lc-1",
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
    ]
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    _mock_ratecon_gate_pass(lifecycle)
    svc = PodLifecycleIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    with _patch_valid_turvo_get():
        out = await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={"event_type": "email_received", "thread_id": "thread-abc"},
        )

    assert out["shipments_row_id"] == _SHIPMENTS_ROW_UUID
    assert out["shipment_id"] == _TURVO_SHIPMENT
    assert "workflow_lifecycle_id" not in out


@pytest.mark.asyncio
async def test_prepare_email_received_payload_skips_attachment_only() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = []
    shipments = MagicMock()
    shipments.upsert_from_load_id = AsyncMock()
    lifecycle = MagicMock()
    svc = PodLifecycleIngressService(
        communications_service=comms,
        shipments_service=shipments,
        lifecycle_service=lifecycle,
    )

    with pytest.raises(PodEmailIngressSkipped) as exc_info:
        await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={
                "event_type": "email_received",
                "thread_id": "unknown-thread",
                "attachments": [
                    {
                        "name": "62495 bol.pdf",
                        "mime": "application/pdf",
                    }
                ],
            },
        )

    assert exc_info.value.reason == "no_shipment_context"
    shipments.upsert_from_load_id.assert_not_called()
    lifecycle.read_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_email_received_payload_skips_without_ratecon_lifecycle() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "ratecon-lc-1",
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
    ]
    lifecycle = MagicMock()
    lifecycle.read_lifecycle.return_value = {"found": False}
    svc = PodLifecycleIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    with pytest.raises(PodEmailIngressSkipped) as exc_info:
        await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={"event_type": "email_received", "thread_id": "thread-abc"},
        )

    assert exc_info.value.reason == "no_ratecon_workflow_lifecycle"
    assert exc_info.value.shipments_row_id == _SHIPMENTS_ROW_UUID
    lifecycle.read_lifecycle.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_name="ratecon",
        shipment_id=_SHIPMENTS_ROW_UUID,
    )


@pytest.mark.asyncio
async def test_prepare_email_received_payload_skips_no_shipment_context() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = []
    shipments = MagicMock()
    shipments.upsert_from_load_id = AsyncMock()
    svc = PodLifecycleIngressService(
        communications_service=comms,
        shipments_service=shipments,
    )

    with pytest.raises(PodEmailIngressSkipped) as exc_info:
        await svc.prepare_email_received_payload(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            payload={"event_type": "email_received", "thread_id": "orphan-thread"},
        )

    assert exc_info.value.reason == "no_shipment_context"
    shipments.upsert_from_load_id.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_email_received_payload_skips_invalid_shipment_status() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "ratecon-lc-1",
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
    ]
    lifecycle = MagicMock()
    _mock_ratecon_gate_pass(lifecycle)
    svc = PodLifecycleIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    with patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        return_value=_valid_turvo_shipment("2102"),
    ):
        with pytest.raises(PodEmailIngressSkipped) as exc_info:
            await svc.prepare_email_received_payload(
                tenant_id=_TENANT_UUID,
                tenant_slug="t3ra",
                payload={"event_type": "email_received", "thread_id": "thread-abc"},
            )

    assert exc_info.value.reason == POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS
    assert exc_info.value.shipments_row_id == _SHIPMENTS_ROW_UUID


@pytest.mark.asyncio
async def test_prepare_email_received_payload_skips_turvo_fetch_failed() -> None:
    comms = MagicMock()
    comms.find_shipment_context_for_thread.return_value = [
        {
            "lifecycle_id": "ratecon-lc-1",
            "workflow_name": "ratecon",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
            "shipment_number": _TURVO_SHIPMENT,
        },
    ]
    lifecycle = MagicMock()
    _mock_ratecon_gate_pass(lifecycle)
    svc = PodLifecycleIngressService(
        communications_service=comms,
        lifecycle_service=lifecycle,
    )

    with patch(
        "app.services.pod_lifecycle.ingress_service.get_shipment",
        new_callable=AsyncMock,
        side_effect=RuntimeError("turvo timeout"),
    ):
        with pytest.raises(PodEmailIngressSkipped) as exc_info:
            await svc.prepare_email_received_payload(
                tenant_id=_TENANT_UUID,
                tenant_slug="t3ra",
                payload={"event_type": "email_received", "thread_id": "thread-abc"},
            )

    assert exc_info.value.reason == POD_EMAIL_SKIP_TURVO_FETCH_FAILED
    assert exc_info.value.shipments_row_id == _SHIPMENTS_ROW_UUID
