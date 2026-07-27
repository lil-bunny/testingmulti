"""Unit tests for Gelita shipper-domain email helpers."""

from __future__ import annotations

from app.domain.gelita.shipper_email import (
    is_gelita_shipper_email,
    reply_from_email_from_state_data,
)


def test_is_gelita_shipper_email_matches_domain() -> None:
    assert is_gelita_shipper_email("ops@gelita.com")
    assert is_gelita_shipper_email("Ops@Gelita.COM")
    assert is_gelita_shipper_email("desk@mail.gelita.com")
    assert not is_gelita_shipper_email("ops@outlook.com")
    assert not is_gelita_shipper_email("carrier@gmail.com")
    assert not is_gelita_shipper_email("not-an-email")
    assert not is_gelita_shipper_email(None)


def test_reply_from_email_prefers_from_attendee() -> None:
    assert (
        reply_from_email_from_state_data(
            {
                "from_attendee": {"identifier": "ops@gelita.com"},
                "from": "other@example.com",
            }
        )
        == "ops@gelita.com"
    )
    assert reply_from_email_from_state_data({"from": "ops@gelita.com"}) == "ops@gelita.com"
    assert reply_from_email_from_state_data({}) is None
