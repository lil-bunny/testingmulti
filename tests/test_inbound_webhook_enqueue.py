"""Unit tests for Redis-first Unipile Ingress path accept helper."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.domain.ingress_result import IngressResult
from app.domain.unipile_email import extract_email_id_or_none
from app.services.inbound_webhook_enqueue import accept_inbound_unipile_email


def test_extract_email_id_or_none() -> None:
    assert extract_email_id_or_none({"email_id": " mail-1 "}) == "mail-1"
    assert extract_email_id_or_none({}) is None
    assert extract_email_id_or_none({"email_id": "  "}) is None


@pytest.mark.asyncio
async def test_accept_calls_process() -> None:
    with patch(
        "app.services.inbound_webhook_enqueue.process_inbound_unipile_email",
        new_callable=AsyncMock,
    ) as mock_process:
        mock_process.return_value = IngressResult(
            outcome="enqueued",
            execution_ids=("exec-1",),
        )
        email_id, status = await accept_inbound_unipile_email(
            tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            tenant_slug="t3ra",
            payload={"email_id": "mail-1"},
        )
    assert email_id == "mail-1"
    assert status == "accepted"
    mock_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_raises_when_email_id_missing() -> None:
    with pytest.raises(ValueError, match="email_id"):
        await accept_inbound_unipile_email(
            tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            tenant_slug="gelita",
            payload={},
        )
