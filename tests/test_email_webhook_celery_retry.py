"""Celery retry policy for background email webhook ingest."""

from __future__ import annotations

from app.services.unipile_service import UnipileException
from app.tasks.email import _EMAIL_WEBHOOK_RETRY_KWARGS, run_email_webhook


def test_run_email_webhook_autoretry_for_unipile_only() -> None:
    assert run_email_webhook.autoretry_for == (UnipileException,)


def test_run_email_webhook_retry_kwargs_fixed_sixty_second_delay() -> None:
    assert run_email_webhook.retry_kwargs == _EMAIL_WEBHOOK_RETRY_KWARGS
    assert run_email_webhook.retry_kwargs["max_retries"] == 3
    assert run_email_webhook.retry_kwargs["countdown"] == 60


def test_run_email_webhook_uses_jitter_and_countdown_not_backoff_kwarg() -> None:
    assert run_email_webhook.retry_jitter is True
    assert "countdown" in run_email_webhook.retry_kwargs
    # Fixed delay via countdown; exponential retry_backoff is not enabled on the decorator.
    assert run_email_webhook.__dict__.get("retry_backoff") is None
