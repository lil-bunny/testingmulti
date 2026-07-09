"""Tests for T3RA ratecon PDF attachment selection."""

from __future__ import annotations

from app.domain.t3ra.email_attachments import (
    load_id_from_ratecon_attachment_name,
    unipile_ratecon_pdf_attachment,
)


def test_load_id_from_ratecon_attachment_name() -> None:
    assert load_id_from_ratecon_attachment_name("Carrier_rate_confirmation_-__56368.pdf") == "56368"
    assert load_id_from_ratecon_attachment_name("carrier_rate_confirmation_30381.pdf") == "30381"
    assert load_id_from_ratecon_attachment_name("Carrier_rate_confirmation.pdf") is None


def test_unipile_ratecon_pdf_attachment_selection() -> None:
    pdf_payload = {
        "attachments": [
            {
                "id": "att-1",
                "name": "carrier_rate_confirmation_30381.pdf",
                "mime": "application/pdf",
            },
        ],
    }
    attachment = unipile_ratecon_pdf_attachment(pdf_payload)
    assert attachment is not None
    assert attachment["id"] == "att-1"
    assert (
        unipile_ratecon_pdf_attachment(
            {
                "attachments": [
                    {
                        "id": "a1",
                        "name": "carrier_rate_confirmation_1.xlsx",
                        "extension": "xlsx",
                    },
                ],
            }
        )
        is None
    )


def test_unipile_ratecon_pdf_attachment_requires_unipile_id() -> None:
    assert (
        unipile_ratecon_pdf_attachment(
            {
                "attachments": [
                    {"name": "carrier_rate_confirmation_30381.pdf", "mime": "application/pdf"},
                ],
            }
        )
        is None
    )
