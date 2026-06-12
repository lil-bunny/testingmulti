"""Tests for ``resolve_email_data_import_tenant_id`` (payload ``webhook_name`` → tenants.id)."""

from __future__ import annotations

from typing import Optional

import pytest

from app.domain.unipile_email import parse_unipile_webhook_name, resolve_unipile_webhook_base_name
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


@pytest.fixture
def staging_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.data_import_tenant_resolution.settings.ENV", "staging")


@pytest.fixture
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.data_import_tenant_resolution.settings.ENV", "dev")


def test_parse_unipile_webhook_name() -> None:
    assert parse_unipile_webhook_name("gelita_staging") == ("gelita", "staging")
    assert parse_unipile_webhook_name("foo_bar_production") == ("foo_bar", "production")
    assert parse_unipile_webhook_name("gelita") is None


def test_resolve_unipile_webhook_base_name() -> None:
    assert resolve_unipile_webhook_base_name("gelita_DEV", "dev") == "gelita"
    assert resolve_unipile_webhook_base_name("gelita_staging", "production") is None


def test_resolver_returns_uuid_when_env_suffix_matches(staging_env: None) -> None:
    fake = _FakeTenantsRepo("uuid-from-db")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita_staging"},
        tenants_repo=fake,
    )
    assert tid == "uuid-from-db"
    assert fake.seen_hook == "gelita"


def test_resolver_passes_base_name_to_repo(dev_env: None) -> None:
    fake = _FakeTenantsRepo("same-uuid")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "  acme_lt_dev  "},
        tenants_repo=fake,
    )
    assert tid == "same-uuid"
    assert fake.seen_hook == "acme_lt"


def test_resolver_returns_none_when_env_mismatch(staging_env: None) -> None:
    fake = _FakeTenantsRepo("uuid-from-db")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita_production"},
        tenants_repo=fake,
    )
    assert tid is None
    assert fake.seen_hook is None


def test_resolver_returns_none_for_unsuffixed_webhook_name(dev_env: None) -> None:
    fake = _FakeTenantsRepo("uuid-from-db")
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita"},
        tenants_repo=fake,
    )
    assert tid is None


def test_resolver_returns_none_when_repo_empty(dev_env: None) -> None:
    fake = _FakeTenantsRepo(None)
    tid = resolve_email_data_import_tenant_id(
        payload={"webhook_name": "gelita_dev"},
        tenants_repo=fake,
    )
    assert tid is None
    assert fake.seen_hook == "gelita"


def test_resolver_returns_none_when_webhook_name_missing() -> None:
    fake = _FakeTenantsRepo("ignored-if-nonblank")
    tid = resolve_email_data_import_tenant_id(payload={}, tenants_repo=fake)
    assert tid is None
    assert fake.seen_hook is None
