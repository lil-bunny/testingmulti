"""Celery task contract for the Pre-Lifecycle Work Queue consumer (``run_email_webhook``)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.tasks.email import _FAILED_EMAIL_INGRESS_KEY, run_email_webhook


def test_run_email_webhook_has_no_celery_autoretry() -> None:
    """Fails fast like ``run_workflow_async``; no Celery-level autoretry (ADR 0001)."""
    assert not getattr(run_email_webhook, "autoretry_for", None)
    assert run_email_webhook.__dict__.get("retry_backoff") is None


def test_run_email_webhook_calls_handler_and_releases_queue_on_success() -> None:
    with (
        patch("app.tasks.email.get_email_webhook_handler") as mock_get_handler,
        patch(
            "app.services.email_ingress_work_queue_serializer_service."
            "EmailIngressWorkQueueSerializerService"
        ) as mock_serializer_cls,
    ):
        async def _handler(*, tenant_uuid: str, tenant_slug: str, payload: dict) -> None:
            return None

        mock_get_handler.return_value = _handler
        mock_serializer = mock_serializer_cls.return_value

        run_email_webhook(
            "inbound.unipile_email",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1"},
            email_id="mail-1",
        )

        mock_serializer.complete_and_start_next.assert_called_once_with(email_id="mail-1")


def test_run_email_webhook_logs_failure_and_releases_queue_then_reraises() -> None:
    with (
        patch("app.tasks.email.get_email_webhook_handler") as mock_get_handler,
        patch("app.integrations.redis.client.get_redis_client") as mock_get_redis,
        patch(
            "app.services.email_ingress_work_queue_serializer_service."
            "EmailIngressWorkQueueSerializerService"
        ) as mock_serializer_cls,
    ):
        async def _handler(**_kwargs: object) -> None:
            raise RuntimeError("boom")

        mock_get_handler.return_value = _handler
        mock_redis = mock_get_redis.return_value
        mock_serializer = mock_serializer_cls.return_value

        with pytest.raises(RuntimeError, match="boom"):
            run_email_webhook(
                "inbound.unipile_email",
                tenant_uuid="tenant-1",
                tenant_slug="gelita",
                payload={"email_id": "mail-1"},
                email_id="mail-1",
            )

        mock_redis.rpush.assert_called_once()
        assert mock_redis.rpush.call_args.args[0] == _FAILED_EMAIL_INGRESS_KEY
        mock_serializer.complete_and_start_next.assert_called_once_with(email_id="mail-1")
