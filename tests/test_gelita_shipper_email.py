"""Unit tests for Gelita shipper-domain email helpers."""

from __future__ import annotations

from app.domain.gelita.shipper_email import (
    email_domain,
    is_shipper_domain_email,
    reply_from_email_from_state_data,
    shipper_domain_from_tenant_settings,
)


def test_email_domain() -> None:
    assert email_domain("ops@gelita.com") == "gelita.com"
    assert email_domain("Ops@Gelita.COM") == "gelita.com"
    assert email_domain("not-an-email") is None
    assert email_domain(None) is None


def test_is_shipper_domain_email_matches_configured_domain() -> None:
    assert is_shipper_domain_email("ops@gelita.com", shipper_domain="gelita.com")
    assert is_shipper_domain_email("Ops@Gelita.COM", shipper_domain="gelita.com")
    assert is_shipper_domain_email("desk@mail.gelita.com", shipper_domain="gelita.com")
    assert not is_shipper_domain_email("ops@outlook.com", shipper_domain="gelita.com")
    assert not is_shipper_domain_email("carrier@gmail.com", shipper_domain="gelita.com")
    assert not is_shipper_domain_email("not-an-email", shipper_domain="gelita.com")
    assert not is_shipper_domain_email(None, shipper_domain="gelita.com")
    assert not is_shipper_domain_email("ops@gelita.com", shipper_domain=None)
    assert not is_shipper_domain_email("ops@gelita.com", shipper_domain="")


def test_shipper_domain_from_inbound_routing_emails() -> None:
    assert (
        shipper_domain_from_tenant_settings(
            {"tenant_settings": {"inbound_routing_emails": ["ayush@freightx.ai"]}}
        )
        == "freightx.ai"
    )
    assert (
        shipper_domain_from_tenant_settings(
            {"tenant_settings": {"inbound_routing_emails": ["Ops@Gelita.COM"]}}
        )
        == "gelita.com"
    )
    assert shipper_domain_from_tenant_settings({"tenant_settings": {}}) is None
    assert shipper_domain_from_tenant_settings({}) is None


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
