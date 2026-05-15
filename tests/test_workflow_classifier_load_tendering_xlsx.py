"""Tests for load-tendering Unipile classification (webhook_name → tenants row + .xlsx)."""

from __future__ import annotations

import pytest

from app.services.workflow_classifier_service import (
    WorkflowClassifierService,
    _is_load_tendering_unipile,
    email_first_attachment,
    unipile_first_attachment_by_extension,
)

_LOAD_TENDER_WEBHOOK = "load_tender_test_hook"


def sample_payload(*, attach_ext: tuple[str, ...] | None = ("pdf", "xlsx")) -> dict:
    attachments = []
    for i, ext in enumerate(attach_ext or ()):
        attachments.append(
            {
                "id": f"aid-{i}",
                "name": f"file{i}.{ext}",
                "extension": ext,
                "mime": "application/octet-stream",
            }
        )
    return {
        "webhook_name": _LOAD_TENDER_WEBHOOK,
        "account_id": "any-unipile-account",
        "has_attachments": True,
        "attachments": attachments,
    }


@pytest.fixture
def mapped_load_tender_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_lookup(name: str) -> str | None:
        return "db-tenant-uuid" if name == _LOAD_TENDER_WEBHOOK else None

    monkeypatch.setattr(
        "app.services.workflow_classifier_service.find_tenant_id_by_settings_email_webhook_name",
        fake_lookup,
    )


def test_email_first_attachment_returns_first_dict_with_id() -> None:
    p = sample_payload(attach_ext=("pdf",))
    att = email_first_attachment(p)
    assert att is not None
    assert att.get("extension") == "pdf"
    assert att.get("id") == "aid-0"


def test_email_first_attachment_skips_attachments_without_id() -> None:
    p = {
        "webhook_name": _LOAD_TENDER_WEBHOOK,
        "attachments": [
            {"name": "a.pdf", "extension": "pdf"},
            {"id": "ok", "name": "b.xlsx", "extension": "xlsx"},
        ],
        "account_id": "x",
        "has_attachments": True,
    }
    att = email_first_attachment(p)
    assert att is not None
    assert att.get("id") == "ok"


def test_unipile_first_attachment_by_extension_skips_prior_non_xlsx() -> None:
    p = sample_payload()
    att = unipile_first_attachment_by_extension(p, "xlsx")
    assert att is not None
    assert att.get("extension") == "xlsx"
    assert att.get("name") == "file1.xlsx"


def test_unipile_first_attachment_by_extension_returns_none_when_no_match() -> None:
    p = sample_payload(attach_ext=("pdf",))
    assert unipile_first_attachment_by_extension(p, "xlsx") is None


def test_is_load_tendering_when_webhook_maps_and_xlsx_present(
    mapped_load_tender_webhook: None,
) -> None:
    p = sample_payload()
    assert _is_load_tendering_unipile(p) is True


def test_is_load_tendering_false_when_webhook_not_in_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workflow_classifier_service.find_tenant_id_by_settings_email_webhook_name",
        lambda _: None,
    )
    assert _is_load_tendering_unipile(sample_payload()) is False


def test_classifier_returns_load_tendering_when_mapped_xlsx(
    mapped_load_tender_webhook: None,
) -> None:
    svc = WorkflowClassifierService()
    assert svc.classify_workflow_type(sample_payload()) == {"workflow_name": "load_tendering"}
