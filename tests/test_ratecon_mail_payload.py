"""Tests for ``app.tools.email.check_ratecon_mail_payload`` (Unipile webhook shape)."""

from __future__ import annotations

from app.tools.email import check_ratecon_mail_payload


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


def test_check_ratecon_mail_payload_positive_sample():
    out = check_ratecon_mail_payload(_sample_unipile_payload())
    assert out["is_ratecon_mail"] is True
    assert out["load_id"] == "56368"
    assert out["subject"] == "Rate confirmation for shipment: #59683"
    assert out["thread_id"] == "sample-thread-id"
    assert out["attachment_name"] == "Carrier_rate_confirmation_-__56368.pdf"
    assert out["attachment_uri"] is None
    assert out["attachment_id"] == "att1"
    assert out["attachment_mime"] == "application/pdf"
    assert out["attachment_unipile"] == {
        "id": "att1",
        "name": "Carrier_rate_confirmation_-__56368.pdf",
        "mime": "application/pdf",
        "extension": "pdf",
    }
    assert out["unipile_attachment_fetch"] == {
        "email_id": "YPNSu5tsW32vaasFc4Rv_Q",
        "account_id": "FqA0zzsTQJ-5naFro793wQ",
        "attachment_id": "att1",
    }


def test_check_ratecon_mail_payload_realistic_unipile_shape():
    """mail_received attachments: id, name, mime, extension, size — no URL."""
    payload = {
        "email_id": "w3M0L_3pW7us8vCCqCzz6w",
        "account_id": "FqA0zzsTQJ-5naFro793wQ",
        "subject": "Rate confirmation for shipment: #30381",
        "has_attachments": True,
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
    out = check_ratecon_mail_payload(payload)
    assert out["is_ratecon_mail"] is True
    assert out["load_id"] == "30381"
    assert out["thread_id"] == (
        "AAQkADY3YzkyMzZmLWM0MWMtNGJjNy05OGNhLTVlYjY1NmU4MWJjNQAQAMDQltZQqi1JrTLP7avn8rE="
    )
    assert out["attachment_uri"] is None
    assert out["attachment_unipile"]["size"] == 48124
    assert out["unipile_attachment_fetch"]["attachment_id"] == "AAMkLONG"


def test_check_ratecon_mail_payload_includes_attachment_uri_when_present():
    p = _sample_unipile_payload()
    p["attachments"][0]["url"] = "https://example.com/file.pdf"
    out = check_ratecon_mail_payload(p)
    assert out["is_ratecon_mail"] is True
    assert out["attachment_uri"] == "https://example.com/file.pdf"


def test_check_ratecon_mail_payload_subject_case_insensitive():
    p = _sample_unipile_payload()
    p["subject"] = "RATE CONFIRMATION for shipment"
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is True


def test_check_ratecon_mail_payload_negative_has_null_attachment_fields():
    out = check_ratecon_mail_payload(
        {"subject": "Rate confirmation x", "has_attachments": False, "attachments": []}
    )
    assert out["attachment_name"] is None
    assert out["attachment_uri"] is None
    assert out["attachment_id"] is None
    assert out["attachment_mime"] is None
    assert out["attachment_unipile"] is None
    assert out["unipile_attachment_fetch"] is None
    assert out["thread_id"] is None


def test_check_ratecon_mail_payload_wrong_subject():
    p = _sample_unipile_payload()
    p["subject"] = "Invoice attached"
    out = check_ratecon_mail_payload(p)
    assert out["is_ratecon_mail"] is False
    assert out["load_id"] is None
    assert out["attachment_name"] is None
    assert out["attachment_uri"] is None
    assert out["attachment_id"] is None
    assert out["thread_id"] == "sample-thread-id"


def test_check_ratecon_mail_payload_no_attachments():
    p = _sample_unipile_payload()
    p["has_attachments"] = False
    p["attachments"] = []
    out = check_ratecon_mail_payload(p)
    assert out["is_ratecon_mail"] is False


def test_check_ratecon_mail_payload_infers_has_attachments_when_none():
    p = _sample_unipile_payload()
    del p["has_attachments"]
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is True


def test_check_ratecon_mail_payload_missing_filename_pattern():
    p = _sample_unipile_payload()
    p["attachments"][0]["name"] = "other.pdf"
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is False


def test_check_ratecon_mail_payload_non_pdf_rejected():
    p = _sample_unipile_payload()
    p["attachments"][0]["name"] = "Carrier_rate_confirmation_-__56368.jpg"
    p["attachments"][0]["mime"] = "image/jpeg"
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is False


def test_check_ratecon_mail_payload_pdf_by_mime_only():
    p = _sample_unipile_payload()
    p["attachments"][0]["name"] = "Carrier_rate_confirmation_-__99"
    p["attachments"][0]["mime"] = "application/pdf"
    assert check_ratecon_mail_payload(p)["load_id"] == "99"


def test_check_ratecon_mail_payload_uses_file_name_keys():
    p = _sample_unipile_payload()
    att = p["attachments"][0]
    del att["name"]
    att["file_name"] = "Carrier_rate_confirmation_-__777.pdf"
    assert check_ratecon_mail_payload(p)["load_id"] == "777"


def test_check_ratecon_mail_payload_no_digits_in_filename():
    p = _sample_unipile_payload()
    p["attachments"][0]["name"] = "Carrier_rate_confirmation.pdf"
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is False


def test_check_ratecon_mail_payload_attachments_not_list():
    p = _sample_unipile_payload()
    p["attachments"] = {}
    p["has_attachments"] = True
    assert check_ratecon_mail_payload(p)["is_ratecon_mail"] is False
