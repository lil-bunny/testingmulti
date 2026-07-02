"""Tests for Unipile send_email from alias support."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.unipile_service import Unipile


@patch("app.services.unipile_service.Unipile._get_headers", return_value={"X-API-KEY": "k"})
def test_send_email_includes_from_recipient_in_form_data(_headers_mock: MagicMock) -> None:
    client = MagicMock()
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = {"tracking_id": "track-1"}
    client.post.return_value = response

    unipile = Unipile()
    unipile.client = client

    unipile.send_email(
        to=[{"identifier": "to@example.com", "display_name": "to"}],
        subject="Hello",
        body="Body",
        account_id="acct-1",
        from_recipient={"identifier": "ops@example.com", "display_name": "ops"},
    )

    posted = client.post.call_args.kwargs["data"]
    assert posted["account_id"] == "acct-1"
    assert '"ops@example.com"' in posted["from"]
