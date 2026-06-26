"""Tests for Turvo public API / UI URL helpers."""

from __future__ import annotations

from app.integrations.turvo.public_api_urls import (
    build_turvo_ui_base_url,
    resolve_turvo_ui_base_url,
)


def test_resolve_turvo_ui_base_url_prefers_explicit() -> None:
    assert (
        resolve_turvo_ui_base_url(
            ui_base_url="https://app.turvo.com/",
            public_api_url="https://my-sandbox-publicapi.turvo.com",
        )
        == "https://app.turvo.com"
    )


def test_resolve_turvo_ui_base_url_falls_back_to_derivation() -> None:
    assert (
        resolve_turvo_ui_base_url(
            ui_base_url=None,
            public_api_url="https://my-sandbox-publicapi.turvo.com",
        )
        == build_turvo_ui_base_url("https://my-sandbox-publicapi.turvo.com")
    )


def test_resolve_turvo_ui_base_url_empty_explicit_falls_back() -> None:
    assert (
        resolve_turvo_ui_base_url(
            ui_base_url="  ",
            public_api_url="https://publicapi.turvo.com",
        )
        == "https://app.turvo.com"
    )
