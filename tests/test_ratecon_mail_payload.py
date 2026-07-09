"""Tests for ratecon Unipile payload classification and attachment selection."""

from __future__ import annotations

from app.domain.t3ra.email_attachments import unipile_ratecon_pdf_attachment
from app.domain.t3ra.email_classification import (
    classify_workflow_type,
    extract_ratecon_metadata_from_payload,
    has_rate_confirmation_subject,
)


def _sample_unipile_payload() -> dict:
    return {
        "event": "mail_received",
        "email_id": "YPNSu5tsW32vaasFc4Rv_Q",
        "account_id": "FqA0zzsTQJ-5naFro793wQ",
        "webhook_name": "langraphmailtest",
        "thread_id": "sample-thread-id",
        "subject": "Rate confirmation for shipment: #59683",
        "has_attachments": True,
        "attachments": [
            {
                "id": "att1",
                "name": "Carrier_rate_confirmation_-__56368.pdf",
                "extension": "pdf",
                "mime": "application/pdf",
            }
        ],
    }


def test_extract_ratecon_metadata_positive_unipile_shapes() -> None:
    """Sample and production-like ``mail_received`` bodies (no attachment URL)."""
    sample = _sample_unipile_payload()
    out_sample = extract_ratecon_metadata_from_payload(sample)
    assert out_sample["is_ratecon_mail"] is True
    assert out_sample["load_id"] == "56368"
    assert out_sample["thread_id"] == "sample-thread-id"
    assert out_sample["ratecon_attachment_name"] == "Carrier_rate_confirmation_-__56368.pdf"
    assert out_sample["ratecon_attachment_uri"] is None
    assert out_sample["ratecon_attachment_id"] == "att1"
    assert out_sample["ratecon_attachment_mime"] == "application/pdf"
    assert out_sample["ratecon_unipile_attachment_fetch"] == {
        "email_id": "YPNSu5tsW32vaasFc4Rv_Q",
        "account_id": "FqA0zzsTQJ-5naFro793wQ",
        "attachment_id": "att1",
    }

    realistic = {
        "email_id": "w3M0L_3pW7us8vCCqCzz6w",
        "account_id": "FqA0zzsTQJ-5naFro793wQ",
        "subject": "Rate confirmation for shipment: #30381",
        "attachments": [
            {
                "id": "AAMkLONG",
                "name": "Carrier_rate_confirmation_-__30381.pdf",
                "extension": "pdf",
                "size": 48124,
                "mime": "application/pdf",
            }
        ],
        "thread_id": "AAQkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQAQAMDQltZQqi1JrTLP7avn8rE=",
    }
    out_real = extract_ratecon_metadata_from_payload(realistic)
    assert out_real["is_ratecon_mail"] is True
    assert out_real["load_id"] == "30381"
    assert out_real["ratecon_attachment_uri"] is None
    assert out_real["ratecon_attachment_unipile"]["size"] == 48124


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
    att = unipile_ratecon_pdf_attachment(pdf_payload)
    assert att is not None
    assert att["id"] == "att-1"
    assert unipile_ratecon_pdf_attachment(
        {
            "attachments": [
                {"id": "a1", "name": "carrier_rate_confirmation_1.xlsx", "extension": "xlsx"},
            ],
        }
    ) is None


def test_extract_ratecon_metadata_attachment_uri_and_filename_keys() -> None:
    payload = _sample_unipile_payload()
    payload["attachments"][0]["url"] = "https://example.com/file.pdf"
    assert extract_ratecon_metadata_from_payload(payload)["ratecon_attachment_uri"] == (
        "https://example.com/file.pdf"
    )

    payload_with_file_name = _sample_unipile_payload()
    attachment = payload_with_file_name["attachments"][0]
    del attachment["name"]
    attachment["file_name"] = "Carrier_rate_confirmation_-__777.pdf"
    assert extract_ratecon_metadata_from_payload(payload_with_file_name)["load_id"] == "777"


def test_extract_ratecon_metadata_rejects_invalid_attachments() -> None:
    payload = _sample_unipile_payload()
    payload["attachments"][0]["name"] = "other.pdf"
    assert extract_ratecon_metadata_from_payload(payload)["is_ratecon_mail"] is False

    payload = _sample_unipile_payload()
    payload["attachments"][0]["name"] = "Carrier_rate_confirmation_-__56368.jpg"
    payload["attachments"][0]["mime"] = "image/jpeg"
    assert extract_ratecon_metadata_from_payload(payload)["is_ratecon_mail"] is False

    payload = _sample_unipile_payload()
    payload["attachments"][0]["name"] = "Carrier_rate_confirmation.pdf"
    assert extract_ratecon_metadata_from_payload(payload)["is_ratecon_mail"] is False

    payload = _sample_unipile_payload()
    payload["attachments"] = {}
    assert extract_ratecon_metadata_from_payload(payload)["is_ratecon_mail"] is False

    assert extract_ratecon_metadata_from_payload({"attachments": []})["is_ratecon_mail"] is False


def test_has_rate_confirmation_subject() -> None:
    assert has_rate_confirmation_subject("Rate confirmation for shipment") is True
    assert has_rate_confirmation_subject("RATE CONFIRMATION for shipment") is True
    assert has_rate_confirmation_subject("Invoice attached") is False
    assert has_rate_confirmation_subject("Rate confirmation TONU for shipment") is False
    assert has_rate_confirmation_subject("TONU - Rate confirmation #12345") is False
    assert has_rate_confirmation_subject("Revised Rate confirmation for shipment") is False
    assert has_rate_confirmation_subject("Rate confirmation (REVISED) #30389") is False


def test_extract_ratecon_metadata_rejects_tonu_subject() -> None:
    payload = _sample_unipile_payload()
    payload["subject"] = "Rate confirmation TONU for shipment: #59683"
    assert extract_ratecon_metadata_from_payload(payload)["is_ratecon_mail"] is False


def test_classify_workflow_type_rejects_tonu_subject() -> None:
    payload = _sample_unipile_payload()
    payload["subject"] = "Rate confirmation TONU for shipment: #59683"
    assert classify_workflow_type(payload) is None
