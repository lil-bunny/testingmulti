"""Tests for app.tools.jwt_tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.tools.jwt_tokens import expires_at_from_bearer_token


def _encode(exp_offset_seconds: int) -> str:
    exp = int(
        (datetime.now(timezone.utc) + timedelta(seconds=exp_offset_seconds)).timestamp()
    )
    return jwt.encode({"exp": exp}, "secret", algorithm="HS256")


def test_expires_at_from_bearer_token_reads_exp() -> None:
    token = _encode(3600)
    expires_at = expires_at_from_bearer_token(token)
    assert expires_at is not None
    assert expires_at > datetime.now(timezone.utc) + timedelta(minutes=59)


def test_expires_at_from_bearer_token_strips_bearer_prefix() -> None:
    token = _encode(3600)
    expires_at = expires_at_from_bearer_token(f"Bearer {token}")
    assert expires_at is not None


def test_expires_at_from_bearer_token_returns_none_for_non_jwt() -> None:
    assert expires_at_from_bearer_token("not-a-jwt") is None


def test_expires_at_from_bearer_token_returns_none_without_exp_claim() -> None:
    token = jwt.encode({"sub": "user"}, "secret", algorithm="HS256")
    assert expires_at_from_bearer_token(token) is None
