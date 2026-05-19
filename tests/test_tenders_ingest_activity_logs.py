"""Activity log side effects during tender ingest."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.tenders_ingest_service import TendersIngestService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENDER_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DATA_IMPORT_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _projected_row() -> dict:
    return {
        "order_number": "ORD-1",
        "customer_match": "Acme Corp",
        "product_name": "Widget",
        "order_quantity": Decimal("100"),
    }


@patch("app.services.tenders_ingest_service.ActivityLogService")
@patch("app.services.tenders_ingest_service.projected_row_to_tender_insert")
def test_ingest_records_two_activity_logs_per_tender(
    mock_map: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    mock_map.return_value = {
        "order_number": "ORD-1",
        "customer_name": "Acme Corp",
        "product_name": "Widget",
        "order_quantity": Decimal("100"),
        "shipping_date": None,
        "delivery_date": None,
        "pickup_location_id": None,
        "delivery_location_id": None,
        "pack_code_id": None,
        "status": "po_imported",
        "load_type": "ltl",
    }
    mock_repo = MagicMock()
    mock_repo.insert_batch.return_value = [TENDER_UUID]
    mock_activity = MagicMock()
    mock_activity_cls.return_value = mock_activity

    svc = TendersIngestService(repository=mock_repo)
    out = svc.persist_from_projected_rows(
        tenant_id=TENANT_UUID,
        data_import_id=DATA_IMPORT_UUID,
        projected_rows=[_projected_row()],
    )

    assert out == [TENDER_UUID]
    mock_activity.record_tender_created_action.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        order_number="ORD-1",
        customer_name="Acme Corp",
    )
    mock_activity.record_tender_processing_status_change.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
    )
    calls = [c[0] for c in mock_activity.method_calls]
    assert calls.index("record_tender_created_action") < calls.index(
        "record_tender_processing_status_change"
    )


@patch(
    "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_record_tender_created_action_fields(mock_resolve: MagicMock) -> None:
    from app.domain.activity_log_constants import NONE_STATUS
    from app.services.activity_log_service import ActivityLogService

    mock_repo = MagicMock()
    mock_repo.insert.return_value = "log-id-1"
    svc = ActivityLogService(repository=mock_repo)

    svc.record_tender_created_action(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        order_number="ORD-1",
        customer_name="Acme Corp",
    )

    row = mock_repo.insert.call_args[0][0]
    assert row["activity_type"] == "action"
    assert "ORD-1" in row["description"]
    assert "Acme Corp" in row["description"]
    assert row["from_status"] == NONE_STATUS
    assert row["to_status"] == NONE_STATUS
    assert row["from_sub_status"] == NONE_STATUS
    assert row["to_sub_status"] == NONE_STATUS
    assert row["actor_type"] == "system"
    assert row["workflow_lifecycle_id"] is None
    assert row["workflow_run_id"] is None


@patch(
    "app.services.activity_log_service.resolve_graph_tenant_to_uuid",
    return_value=TENANT_UUID,
)
def test_record_tender_processing_status_change_uses_transaction(
    mock_resolve: MagicMock,
) -> None:
    from app.domain.activity_log_constants import NONE_STATUS
    from app.services.activity_log_service import ActivityLogService

    mock_repo = MagicMock()
    svc = ActivityLogService(repository=mock_repo)

    svc.record_tender_processing_status_change(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
    )

    mock_repo.insert.assert_not_called()
    mock_repo.apply_tender_processing_with_status_change_log.assert_called_once()
    _, kwargs = mock_repo.apply_tender_processing_with_status_change_log.call_args
    assert kwargs["tenant_id"] == TENANT_UUID
    assert kwargs["tender_id"] == TENDER_UUID
    log_row = kwargs["log_row"]
    assert log_row["activity_type"] == "status_change"
    assert log_row["to_status"] == "processing"
    assert log_row["to_sub_status"] == "tender_created"
    assert log_row["from_status"] == NONE_STATUS
