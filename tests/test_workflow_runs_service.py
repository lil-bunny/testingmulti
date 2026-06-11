"""Tests for WorkflowRunsService dedupe / shipment correlation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.workflow_runs_service import WorkflowRunsService


def test_is_workflow_initial_path_blocked_external_shipment_number_no_uuid_cast() -> None:
    """External shipment number must not be compared to workflow_lifecycles.shipment_id UUID."""
    svc = WorkflowRunsService()
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (False,)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch.object(svc, "_conn", return_value=mock_conn), patch.object(
        svc, "_tenant_uuid_or_none", return_value="00000000-0000-4000-8000-0000000000e1"
    ):
        blocked = svc.is_workflow_initial_path_blocked(
            tenant_id="t3ra",
            event_type="route_completed",
            workflow_lifecycle_id="11111111-2222-3333-4444-555555555555",
            shipment_id="1000324895",
            exclude_run_id="b17b2fd8-aafc-4020-980c-dd47a0d5353a",
        )

    assert blocked is False
    mock_cur.execute.assert_called_once()
    sql = mock_cur.execute.call_args[0][0]
    assert "s.shipment_number = %s" in sql
    assert "wl.shipment_id IS NOT DISTINCT FROM %s::uuid" in sql
    params = mock_cur.execute.call_args[0][1]
    assert "1000324895" in params
    assert params[8] is None  # shipment_uuid branch disabled for Turvo id
