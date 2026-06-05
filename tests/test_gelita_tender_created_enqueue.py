"""Gelita Excel ingest: enqueue load_tendering only for newly created tenders."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.responses import JSONResponse

from app.services.gelita_inbound_email_service import GelitaInboundEmailService
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
                "name": "loads.xlsx",
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
    "app.services.load_tendering_email_ingest_service.process_email_webhook_attachment_import"
)
async def test_tender_created_skips_enqueue_when_order_already_exists(
    mock_import: AsyncMock,
    mock_projection: MagicMock,
    mock_persist: MagicMock,
    mock_celery: MagicMock,
) -> None:
    mock_import.return_value = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    mock_projection.return_value = [
        {"order_number": "93384"},
        {"order_number": "95009"},
    ]
    mock_persist.return_value = [None, "dddddddd-dddd-dddd-dddd-dddddddddddd"]

    mock_task = MagicMock()
    mock_task.apply_async.return_value = MagicMock(id="celery-1")
    mock_celery.apply_async = mock_task.apply_async

    result = await process_tender_created_from_email_webhook(
        payload={"thread_id": "thr-1", "webhook_name": "gelita"},
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
        graph_slug="gelita",
    )

    assert len(result["execution_ids"]) == 1
    assert mock_task.apply_async.call_count == 1
    wp = mock_task.apply_async.call_args.kwargs["kwargs"]["payload"]
    assert wp["tender_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert wp["order_number"] == "95009"
    assert wp["event_type"] == "tender_created"


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
    mock_import: AsyncMock,
    mock_projection: MagicMock,
    mock_persist: MagicMock,
    mock_celery: MagicMock,
) -> None:
    mock_import.return_value = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
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
@patch("app.services.gelita_inbound_email_service.enqueue_load_tendering_tender_created_ingest")
@patch("app.services.gelita_inbound_email_service.CommunicationsService.record_or_resolve_inbound")
async def test_handle_xlsx_enqueues_background_ingest_not_inline_import(
    mock_record: MagicMock,
    mock_enqueue_ingest: MagicMock,
) -> None:
    mock_enqueue_ingest.return_value = ("task-abc", "queued")

    svc = GelitaInboundEmailService()
    response = await svc.handle(payload=_xlsx_payload(), tenant=_tenant())

    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "accepted"
    assert content["event_type"] == "tender_created"
    assert content["task_id"] == "task-abc"
    assert content["status"] == "queued"
    mock_enqueue_ingest.assert_called_once()
    mock_record.assert_called_once()
