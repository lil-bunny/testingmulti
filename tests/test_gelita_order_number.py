"""Gelita carrier email order number extraction."""

from __future__ import annotations

from app.tools.gelita.order_number import extract_order_number

_GMAIL_FORWARD_BODY = (
    '<div dir="ltr"><br><br>'
    '<div class="gmail_quote gmail_quote_container">'
    '<div dir="ltr" class="gmail_attr">---------- Forwarded message ---------'
    "<br>Subject: PICK UP REQUEST # 96385 PO# COL-13<br></div><br><br>"
    '<div style="font-family:Arial,Helvetica,sans-serif">'
    '<p style="margin-bottom:0">Order #96385<br>Customer PO #COL-13</p>'
    "</div></div></div>"
)


def test_extract_order_number_from_direct_html_body() -> None:
    assert extract_order_number("<p>Order #93795</p>") == "93795"


def test_extract_order_number_from_gmail_forward_body() -> None:
    assert extract_order_number(_GMAIL_FORWARD_BODY) == "96385"


def test_extract_order_number_returns_none_when_missing() -> None:
    assert extract_order_number("Thanks, we will review.") is None
    assert extract_order_number(None) is None
    assert extract_order_number("") is None
