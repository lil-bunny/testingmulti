"""Tests for POD lifecycle tenant settings accessors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.domain.pod_lifecycle.settings import (
    MikeyMailbox,
    hydrate_pod_account_id,
    mikey_unipile_from,
    parse_mikey_mailbox,
    resolve_mikey_mailbox,
    resolve_pod_sender_account_id,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings

_T3RA_SETTINGS = minimal_t3ra_tenant_settings()


def test_parse_mikey_mailbox_string() -> None:
    assert parse_mikey_mailbox("acct-1") == MikeyMailbox(account_id="acct-1")


def test_parse_mikey_mailbox_object_with_alias() -> None:
    assert parse_mikey_mailbox(
        {"account_id": "acct-1", "email_alias": "ops@example.com"}
    ) == MikeyMailbox(account_id="acct-1", email_alias="ops@example.com")


def test_parse_mikey_mailbox_object_without_alias() -> None:
    assert parse_mikey_mailbox({"account_id": "acct-1"}) == MikeyMailbox(
        account_id="acct-1"
    )


def test_mikey_unipile_from_returns_none_without_alias() -> None:
    assert mikey_unipile_from(MikeyMailbox(account_id="acct-1")) is None


def test_mikey_unipile_from_builds_recipient() -> None:
    out = mikey_unipile_from(
        MikeyMailbox(account_id="acct-1", email_alias="ops@example.com")
    )
    assert out == {"identifier": "ops@example.com", "display_name": "ops"}


def test_resolve_prefers_explicit_payload_account_id() -> None:
    data = {
        "account_id": "webhook-account",
        "tenant_settings": {"mikey_account_id": {"account_id": "tenant-account"}},
    }
    mailbox = resolve_mikey_mailbox(data)
    assert mailbox == MikeyMailbox(
        account_id="webhook-account",
        email_alias=None,
    )
    assert resolve_pod_sender_account_id(data) == "webhook-account"


def test_resolve_uses_mikey_account_id_from_tenant_settings() -> None:
    data = {"tenant_settings": _T3RA_SETTINGS}
    assert resolve_pod_sender_account_id(data) == "test-mikey-account-id"
    mailbox = resolve_mikey_mailbox(data)
    assert mailbox == MikeyMailbox(
        account_id="test-mikey-account-id",
        email_alias="ops@example.com",
    )


def test_resolve_falls_back_to_env_when_tenant_missing() -> None:
    with patch("app.domain.pod_lifecycle.settings.settings.UNIPILE_ACCOUNT_ID", "env-account"):
        assert resolve_pod_sender_account_id({}) == "env-account"


def test_hydrate_sets_account_id_on_payload() -> None:
    payload = {"tenant_settings": _T3RA_SETTINGS}
    hydrate_pod_account_id(payload)
    assert payload["account_id"] == "test-mikey-account-id"


def test_hydrate_does_not_override_existing_account_id() -> None:
    payload = {
        "account_id": "keep-me",
        "tenant_settings": _T3RA_SETTINGS,
    }
    hydrate_pod_account_id(payload)
    assert payload["account_id"] == "keep-me"


def test_resolve_from_workflow_state_object() -> None:
    state = SimpleNamespace(
        data={"tenant_settings": _T3RA_SETTINGS},
    )
    assert resolve_pod_sender_account_id(state) == "test-mikey-account-id"
