"""Tests for driver_assignment.partial_follow_up_email tenant config."""

from app.domain.driver_assignment.partial_follow_up_email import (
    DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML,
    parse_driver_assignment_partial_follow_up_email,
    resolve_partial_follow_up_email,
)


def test_parse_generic_keys() -> None:
    conf = parse_driver_assignment_partial_follow_up_email(
        {
            "driver_assignment": {
                "partial_follow_up_email": {
                    "template_html": "<p>Custom chase {load_id}</p>",
                }
            }
        }
    )
    assert conf is not None
    assert conf.body_html() == "<p>Custom chase {load_id}</p>"


def test_resolve_defaults_when_missing() -> None:
    body = resolve_partial_follow_up_email(None)
    assert body == DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML
    assert "complete driver details" in body


def test_resolve_uses_tenant_template() -> None:
    body = resolve_partial_follow_up_email(
        {
            "driver_assignment": {
                "partial_follow_up_email": {
                    "template_html": "<p>Tenant partial body</p>",
                }
            }
        }
    )
    assert body == "<p>Tenant partial body</p>"
