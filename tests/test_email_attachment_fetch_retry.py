"""Transient retry for Unipile email attachment fetch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.email_webhook_attachment_ingestion import (
    fetch_email_attachment_bytes_with_retry,
    is_transient_unipile_error,
)
from app.services.unipile_service import UnipileException


def test_is_transient_unipile_error_detects_504() -> None:
    assert is_transient_unipile_error(UnipileException("Error retrieving attachment: 504"))


@patch("app.services.email_webhook_attachment_ingestion.time.sleep")
def test_fetch_retries_then_succeeds(mock_sleep: MagicMock) -> None:
    calls = {"n": 0}

    def flaky(_e: str, _a: str, _c: str) -> bytes:
        calls["n"] += 1
        if calls["n"] < 3:
            raise UnipileException("request_timeout")
        return b"xlsx-bytes"

    result = fetch_email_attachment_bytes_with_retry(
        email_id="e1",
        attachment_id="a1",
        account_id="acc",
        fetch_fn=flaky,
    )
    assert result == b"xlsx-bytes"
    assert calls["n"] == 3
    assert mock_sleep.call_count == 2


@patch("app.services.email_webhook_attachment_ingestion.time.sleep")
def test_fetch_raises_after_transient_exhausted(mock_sleep: MagicMock) -> None:
    def always_fail(_e: str, _a: str, _c: str) -> bytes:
        raise UnipileException("504 gateway timeout")

    with pytest.raises(UnipileException):
        fetch_email_attachment_bytes_with_retry(
            email_id="e1",
            attachment_id="a1",
            account_id="acc",
            fetch_fn=always_fail,
        )
