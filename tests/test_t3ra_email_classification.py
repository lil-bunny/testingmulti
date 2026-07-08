"""Tests for T3RA inbound email classification domain."""

from __future__ import annotations

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
    assert metadata["is_ratecon_mail"] is True
    assert metadata["load_id"] == "56368"


def test_has_rate_confirmation_subject() -> None:
    assert has_rate_confirmation_subject("Rate confirmation for shipment") is True
    assert has_rate_confirmation_subject("Invoice attached") is False
