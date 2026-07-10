"""Unit tests for HTTP-edge Unipile ingress enqueue."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.unipile_email import extract_email_id_or_none
from app.services.inbound_webhook_enqueue import (
    build_inbound_ingress_task_id,
    enqueue_inbound_unipile_email,
)


def test_extract_email_id_or_none() -> None:
    assert extract_email_id_or_none({"email_id": " mail-1 "}) == "mail-1"
    assert extract_email_id_or_none({}) is None
    assert extract_email_id_or_none({"email_id": "  "}) is None


def test_build_inbound_ingress_task_id_is_deterministic() -> None:
    tenant_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    email_id = "mail-1"
    first = build_inbound_ingress_task_id(tenant_uuid=tenant_uuid, email_id=email_id)
    second = build_inbound_ingress_task_id(tenant_uuid=tenant_uuid, email_id=email_id)
    assert first == second
    assert first != build_inbound_ingress_task_id(
        tenant_uuid=tenant_uuid,
        email_id="mail-2",
    )


@patch("app.tasks.email.run_email_webhook.apply_async")
def test_enqueue_inbound_unipile_email_queues(mock_apply: MagicMock) -> None:
    task_id, status = enqueue_inbound_unipile_email(
        tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="gelita",
        payload={"email_id": "mail-1"},
    )
    assert status == "queued"
    assert task_id == build_inbound_ingress_task_id(
        tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        email_id="mail-1",
    )
    mock_apply.assert_called_once()
    call_kwargs = mock_apply.call_args.kwargs
    assert call_kwargs["task_id"] == task_id
    assert call_kwargs["kwargs"]["handler"] == "inbound.unipile_email"
    assert call_kwargs["kwargs"]["tenant_slug"] == "gelita"


@patch("app.tasks.email.run_email_webhook.apply_async")
def test_enqueue_inbound_unipile_email_already_queued(mock_apply: MagicMock) -> None:
    mock_apply.side_effect = Exception("task id already exists")
    task_id, status = enqueue_inbound_unipile_email(
        tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="t3ra",
        payload={"email_id": "mail-dup"},
    )
    assert status == "already_queued"
    assert task_id == build_inbound_ingress_task_id(
        tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        email_id="mail-dup",
    )


def test_enqueue_raises_when_email_id_missing() -> None:
    with pytest.raises(ValueError, match="email_id"):
        enqueue_inbound_unipile_email(
            tenant_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            tenant_slug="gelita",
            payload={},
        )
