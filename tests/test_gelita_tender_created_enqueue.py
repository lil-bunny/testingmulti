"""Gelita Excel webhook: enqueue load_tendering only for newly created tenders."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.responses import JSONResponse

from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
    )


@pytest.mark.asyncio
@patch("app.services.gelita_inbound_email_service.run_workflow_async")
@patch(
    "app.services.gelita_inbound_email_service.persist_tender_rows_from_email_import_projection"
)
@patch("app.services.gelita_inbound_email_service.load_email_data_import_projection")
@patch("app.services.gelita_inbound_email_service.process_email_webhook_attachment_import")
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

    svc = GelitaInboundEmailService()
    response = await svc._handle_tender_created(
        payload={"thread_id": "thr-1", "webhook_name": "gelita"},
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert len(content["execution_ids"]) == 1
    assert mock_task.apply_async.call_count == 1
    wp = mock_task.apply_async.call_args.kwargs["kwargs"]["payload"]
    assert wp["tender_id"] == "dddddddd-dddd-dddd-dddd-dddddddddddd"
    assert wp["event_type"] == "tender_created"


@pytest.mark.asyncio
@patch("app.services.gelita_inbound_email_service.run_workflow_async")
@patch(
    "app.services.gelita_inbound_email_service.persist_tender_rows_from_email_import_projection"
)
@patch("app.services.gelita_inbound_email_service.load_email_data_import_projection")
@patch("app.services.gelita_inbound_email_service.process_email_webhook_attachment_import")
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

    svc = GelitaInboundEmailService()
    response = await svc._handle_tender_created(
        payload={"thread_id": "thr-1"},
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    content = json.loads(response.body)
    assert len(content["execution_ids"]) == 1
    assert mock_task.apply_async.call_count == 1
