"""Tests for Gellita load-tendering attachment resolution helpers."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.workflow_classifier_service import (
    WorkflowClassifierService,
    email_first_attachment,
    unipile_first_attachment_by_extension,
    _is_gellita_load_tendering_unipile as is_gellita_load_tendering_unipile,
)


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
        "account_id": "gal-test-account",
        "has_attachments": True,
        "attachments": attachments,
    }


def test_email_first_attachment_returns_first_dict_with_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "", raising=False)
    p = sample_payload(attach_ext=("pdf",))
    att = email_first_attachment(p)
    assert att is not None
    assert att.get("extension") == "pdf"
    assert att.get("id") == "aid-0"


def test_email_first_attachment_skips_attachments_without_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "", raising=False)
    p = {
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


def test_unipile_first_attachment_by_extension_skips_prior_non_xlsx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "", raising=False)
    p = sample_payload()
    att = unipile_first_attachment_by_extension(p, "xlsx")
    assert att is not None
    assert att.get("extension") == "xlsx"
    assert att.get("name") == "file1.xlsx"


def test_unipile_first_attachment_by_extension_returns_none_when_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "", raising=False)
    p = sample_payload(attach_ext=("pdf",))
    assert unipile_first_attachment_by_extension(p, "xlsx") is None


def test_is_gellita_load_tendering_when_account_matches_env_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "gal-test-account", raising=False)
    p = sample_payload()
    assert is_gellita_load_tendering_unipile(p) is True


def test_classifier_returns_load_tendering_when_gellita_xlsx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GELLITA_UNIPILE_ID", "gal-test-account", raising=False)
    svc = WorkflowClassifierService()
    assert svc.classify_workflow_type(sample_payload()) == {"workflow_name": "load_tendering"}
