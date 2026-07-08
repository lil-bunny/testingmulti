"""Gelita Excel ingest: enqueue load_tendering only for newly created tenders."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.gelita_email_ingress_service import GelitaEmailIngressService
from app.services.load_tendering_email_ingest_service import (
    process_tender_created_from_email_webhook,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
    )


def _xlsx_payload() -> dict:
    return {
        "webhook_name": "gelita",
        "email_id": "mail-1",
        "account_id": "acc-1",
        "has_attachments": True,
        "attachments": [
            {
                "id": "att-1",
                "name": "customers_orders_loads.xlsx",
                "extension": "xlsx",
            },
        ],
        "thread_id": "thr-1",
    }


@pytest.mark.asyncio
@patch("app.services.load_tendering_email_ingest_service.run_workflow_async")
@patch(
    "app.services.load_tendering_email_ingest_service.persist_tender_rows_from_email_import_projection"
)
@patch("app.services.load_tendering_email_ingest_service.load_email_data_import_projection")
@patch(
    "app.services.load_tendering_email_ingest_service."
    "process_email_webhook_attachment_import_for_attachment"
)
async def test_tender_created_skips_enqueue_when_order_already_exists(
    mock_attachment_import: AsyncMock,
    mock_projection: MagicMock,
    mock_persist: MagicMock,
    mock_celery: MagicMock,
) -> None:
    mock_attachment_import.return_value = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    mock_projection.return_value = [
        {"order_number": "93384"},
        {"order_number": "95009"},
    ]
    mock_persist.return_value = [None, "dddddddd-dddd-dddd-dddd-dddddddddddd"]

    mock_task = MagicMock()
    mock_task.apply_async.return_value = MagicMock(id="celery-1")
    mock_celery.apply_async = mock_task.apply_async

    load_tendering_xlsx_attachment = {
        "id": "att-1",
        "name": "customers_orders_loads.xlsx",
        "extension": "xlsx",
    }
    result = await process_tender_created_from_email_webhook(
        payload={"thread_id": "thr-1", "webhook_name": "gelita"},
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
        graph_slug="gelita",
        attachment=load_tendering_xlsx_attachment,
    )

    assert len(result["execution_ids"]) == 1
    assert mock_task.apply_async.call_count == 1
    mock_attachment_import.assert_called_once()
    assert (
        mock_attachment_import.call_args.kwargs["attachment"]
        is load_tendering_xlsx_attachment
    )
    workflow_payload = mock_task.apply_async.call_args.kwargs["kwargs"]["payload"]
    assert workflow_payload["tender_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert workflow_payload["order_number"] == "95009"
    assert workflow_payload["event_type"] == "tender_created"


@pytest.mark.asyncio
@patch("app.services.load_tendering_email_ingest_service.run_workflow_async")
@patch(
    "app.services.load_tendering_email_ingest_service.persist_tender_rows_from_email_import_projection"
)
@patch("app.services.load_tendering_email_ingest_service.load_email_data_import_projection")
@patch(
    "app.services.load_tendering_email_ingest_service.process_email_webhook_attachment_import"
)
async def test_tender_created_enqueues_once_for_duplicate_spreadsheet_rows(
    mock_attachment_import: AsyncMock,
    mock_projection: MagicMock,
    mock_persist: MagicMock,
    mock_celery: MagicMock,
) -> None:
    mock_attachment_import.return_value = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    mock_projection.return_value = [
        {"order_number": "93384"},
        {"order_number": "93384"},
    ]
    tender_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    mock_persist.return_value = [tender_id, tender_id]

    mock_task = MagicMock()
    mock_task.apply_async.return_value = MagicMock(id="celery-1")
    mock_celery.apply_async = mock_task.apply_async

    result = await process_tender_created_from_email_webhook(
        payload={"thread_id": "thr-1"},
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
        graph_slug="gelita",
    )

    assert len(result["execution_ids"]) == 1
    assert mock_task.apply_async.call_count == 1


@pytest.mark.asyncio
@patch(
    "app.services.gelita_email_ingress_service.process_tender_created_from_email_webhook",
    new_callable=AsyncMock,
)
async def test_process_xlsx_runs_inline_tender_created_ingest(
    mock_tender_created_from_email_webhook: AsyncMock,
) -> None:
    mock_tender_created_from_email_webhook.return_value = {
        "message": "success",
        "event_type": "tender_created",
        "execution_ids": ["exec-1"],
    }

    svc = GelitaEmailIngressService()
    result = await svc.process(
        payload=_xlsx_payload(),
        tenant=_tenant(),
        communication_id="comm-1",
    )

    assert result.outcome == "enqueued"
    assert result.event_type == "tender_created"
    assert result.execution_ids == ("exec-1",)
    mock_tender_created_from_email_webhook.assert_called_once()
    assert (
        mock_tender_created_from_email_webhook.call_args.kwargs["attachment"]["name"]
        == "customers_orders_loads.xlsx"
    )
