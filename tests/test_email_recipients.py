"""Tests for email recipient normalization."""

from __future__ import annotations

import pytest

from app.domain.tenant_settings.email_recipients import (
    EmailRecipients,
    coerce_email_list,
    email_recipients_from_action_cfg,
    unipile_recipients_from_addresses,
)


def test_coerce_email_list_single_string() -> None:
    assert coerce_email_list("A@b.com", required=True) == ["A@b.com"]


def test_coerce_email_list_dedupes_case_insensitive() -> None:
    assert coerce_email_list(["A@b.com", "a@b.com", "c@d.com"], required=True) == [
        "A@b.com",
        "c@d.com",
    ]


def test_coerce_email_list_required_empty_raises() -> None:
    with pytest.raises(ValueError):
        coerce_email_list([], required=True)


def test_email_recipients_from_action_cfg() -> None:
    rec = email_recipients_from_action_cfg(
        {
            "vendor_email": ["v1@x.com", "v2@x.com"],
            "vendor_cc": "cc@x.com",
            "vendor_bcc": [],
        },
        to_key="vendor_email",
        cc_key="vendor_cc",
        bcc_key="vendor_bcc",
    )
    assert rec.to == ["v1@x.com", "v2@x.com"]
    assert rec.cc == ["cc@x.com"]
    assert rec.bcc == []


def test_email_recipients_from_action_cfg_rejects_empty_to() -> None:
    with pytest.raises(ValueError, match="at least one valid email"):
        email_recipients_from_action_cfg(
            {"vendor_email": [], "vendor_cc": "cc@x.com", "vendor_bcc": []},
            to_key="vendor_email",
            cc_key="vendor_cc",
            bcc_key="vendor_bcc",
        )


def test_unipile_recipients_from_addresses() -> None:
    out = unipile_recipients_from_addresses(["ops@gelita.com"])
    assert out == [{"identifier": "ops@gelita.com", "display_name": "ops"}]


def test_email_recipients_legacy_string_to() -> None:
    rec = EmailRecipients(to="only@x.com")
    assert rec.to == ["only@x.com"]


def test_email_recipients_allows_empty_to() -> None:
    rec = EmailRecipients()
    assert rec.to == []
    assert rec.cc == []
    assert rec.bcc == []


def test_email_recipients_cc_only() -> None:
    rec = EmailRecipients(cc="ops@example.com")
    assert rec.to == []
    assert rec.cc == ["ops@example.com"]
