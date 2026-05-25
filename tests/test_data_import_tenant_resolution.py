"""Tests for ``resolve_email_data_import_tenant_id`` (payload ``webhook_name`` → tenants.id)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.services.data_import_tenant_resolution import resolve_email_data_import_tenant_id


class _FakeTenantsRepo:
    def __init__(self, tid: Optional[str]):
        self.tid = tid
        self.seen_hook: Optional[str] = None

    def find_tenant_id_by_email_webhook_name(self, webhook_name: str) -> Optional[str]:
        self.seen_hook = webhook_name
        if not webhook_name.strip():
            return None
        return self.tid


def test_resolver_returns_uuid_when_repo_present() -> None:
    fake = _FakeTenantsRepo("uuid-from-db")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita"},
        tenants_repo=fake,
    )
    assert tid == "uuid-from-db"
    assert fake.seen_hook == "gelita"


def test_resolver_passes_payload_webhook_name_to_repo_before_strip_matches_db() -> None:
    fake = _FakeTenantsRepo("same-uuid")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "  acme_lt  "},
        tenants_repo=fake,
    )
    assert tid == "same-uuid"
    assert fake.seen_hook == "  acme_lt  "


def test_resolver_returns_none_when_repo_empty() -> None:
    fake = _FakeTenantsRepo(None)
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita"},
        tenants_repo=fake,
    )
    assert tid is None


def test_resolver_returns_none_when_webhook_name_missing() -> None:
    fake = _FakeTenantsRepo("ignored-if-nonblank")
    tid = resolve_email_data_import_tenant_id(payload={}, tenants_repo=fake)
    assert tid is None
    assert fake.seen_hook == ""
