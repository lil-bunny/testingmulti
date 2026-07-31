"""Tests for T3RA inbound email classification domain."""

from __future__ import annotations

import pytest

from app.domain.t3ra.email_classification import (
    classify_t3ra_inbound_email,
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


def test_classify_t3ra_non_rate_confirmation_reply_has_no_workflow() -> None:
    email_classification = classify_t3ra_inbound_email(
        {
            "subject": "Re: driver info",
            "thread_id": "thread-1",
            "in_reply_to": "msg-parent",
        }
    )
    assert email_classification.workflow_name is None
    assert email_classification.is_thread_reply is True


def test_classify_t3ra_pod_reply() -> None:
    email_classification = classify_t3ra_inbound_email(
        {
            "subject": "Rate confirmation POD",
            "has_attachments": True,
            "in_reply_to": "msg-parent",
        }
    )
    assert email_classification.workflow_name == "pod_lifecycle"


def test_classify_workflow_type_rejects_tonu_subject() -> None:
    payload = _sample_unipile_payload()
    payload["subject"] = "Rate confirmation TONU for shipment: #59683"
    assert classify_workflow_type(payload) is None


def test_extract_ratecon_metadata_positive_unipile_shapes() -> None:
    sample = _sample_unipile_payload()
    metadata = extract_ratecon_metadata_from_payload(sample)
    assert metadata["load_id"] == "56368"
    assert set(metadata) == {"load_id", "subject", "thread_id"}


def test_has_rate_confirmation_subject() -> None:
    assert has_rate_confirmation_subject("Rate confirmation for shipment") is True
    assert has_rate_confirmation_subject("Invoice attached") is False


def test_classify_t3ra_inline_photo_reply_is_not_ratecon() -> None:
    """Prod scenario: carrier replies with inline JPEG on a ratecon thread — no workflow."""
    payload = _sample_unipile_payload()
    payload["subject"] = "Re: Rate confirmation for shipment: #63467 TURLOCK, CA, US"
    payload["attachments"] = [
        {"id": "att1", "name": "IMG_4550.jpeg", "extension": "jpeg", "mime": "image/jpeg", "inline": True}
    ]

    email_classification = classify_t3ra_inbound_email(payload)

    assert email_classification.workflow_name is None
    assert email_classification.is_rate_confirmation_subject is True
    assert email_classification.has_attachments is True
    assert email_classification.is_thread_reply is True


@pytest.mark.parametrize(
    "attachment_name",
    ["signed rate con.pdf", "Carrier_rate_confirmation_.pdf"],
    ids=["name_without_load_id_digits", "name_without_trailing_digits"],
)
def test_classify_t3ra_ratecon_requires_parsable_load_id(attachment_name: str) -> None:
    """PDF present but filename doesn't yield a load_id — not a ratecon."""
    payload = _sample_unipile_payload()
    payload["attachments"] = [
        {"id": "att1", "name": attachment_name, "extension": "pdf", "mime": "application/pdf"}
    ]

    result = classify_t3ra_inbound_email(payload)
    assert result.workflow_name is None
    assert result.ratecon_metadata is None
