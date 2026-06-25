"""Tests for Teams Incoming Webhook integration."""

from __future__ import annotations

import pytest
import httpx

from app.integrations.teams.webhook import (
    TeamsWebhookError,
    build_message_card_payload,
    post_message_card,
)


def test_build_message_card_payload_includes_facts() -> None:
    payload = build_message_card_payload(
        title="Escalation",
        text="Please follow up",
        facts=[("Load ID", "30389"), ("Carrier", "Acme")],
    )
    assert payload["title"] == "Escalation"
    assert payload["sections"][0]["text"] == "Please follow up"
    facts = payload["sections"][0]["facts"]
    assert facts[0] == {"name": "Load ID", "value": "30389"}


@pytest.mark.asyncio
async def test_post_message_card_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class _FakeResponse:
        status_code = 200
        text = "1"

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            calls.append({"url": url, "json": json})
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeClient())

    await post_message_card(
        "https://example.webhook.office.com/test",
        title="Title",
        text="Body",
        facts=[("Load ID", "1")],
    )
    assert calls[0]["url"].startswith("https://example.webhook")
    assert calls[0]["json"]["title"] == "Title"


@pytest.mark.asyncio
async def test_post_message_card_raises_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        status_code = 500
        text = "error"

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _FakeClient())

    with pytest.raises(TeamsWebhookError) as exc_info:
        await post_message_card(
            "https://example.webhook.office.com/test",
            title="Title",
            text="Body",
            facts=[],
        )
    assert exc_info.value.status_code == 500
