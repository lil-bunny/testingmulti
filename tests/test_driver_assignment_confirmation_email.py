"""Tests for generic driver_assignment.confirmation_email tenant config."""

from app.domain.driver_assignment.confirmation_email import (
    parse_driver_assignment_confirmation_email,
)


def test_parse_generic_keys() -> None:
    conf = parse_driver_assignment_confirmation_email(
        {
            "driver_assignment": {
                "confirmation_email": {
                    "tracking_customer_names": ["ACME Corp", "USCS CSC"],
                    "tracking_template_html": "<p>track {driver_name}</p>",
                    "default_template_html": "<p>default {driver_phone}</p>",
                    "send_invite_for_tracking": False,
                    "send_invite_for_default": True,
                }
            }
        }
    )
    assert conf is not None
    assert conf.is_tracking_customer("USCS CSC") is True
    assert conf.is_tracking_customer("Other") is False
    assert conf.template_html_for(is_tracking_customer=True) == "<p>track {driver_name}</p>"
    assert conf.template_html_for(is_tracking_customer=False) == "<p>default {driver_phone}</p>"
    assert conf.send_invite_for(is_tracking_customer=True) is False
    assert conf.send_invite_for(is_tracking_customer=False) is True
    assert conf.variant_key_for(is_tracking_customer=True) == "tracking"


def test_parse_legacy_keys() -> None:
    conf = parse_driver_assignment_confirmation_email(
        {
            "driver_assignment": {
                "confirmation_email": {
                    "tracking_customer_name": "USCS CSC",
                    "fourkites_template_html": "<p>legacy tracking</p>",
                    "turvo_app_template_html": "<p>legacy default</p>",
                }
            }
        }
    )
    assert conf is not None
    assert conf.tracking_customer_names == ["USCS CSC"]
    assert conf.tracking_template_html == "<p>legacy tracking</p>"
    assert conf.default_template_html == "<p>legacy default</p>"
