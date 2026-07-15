"""Tests for workflow shadow mode tenant settings helpers."""

from __future__ import annotations

from app.domain.tenant_settings.email_recipients import EmailRecipients
from app.domain.tenant_settings.workflow_shadow_mode import (
    ShadowBypassLoadEntry,
    load_in_shadow_bypass_allowlist,
    parse_shadow_bypass_loads,
    parse_shadow_mail_recipients,
    shadow_mail_metadata_patch,
    shadow_metadata_patch,
    workflow_shadow_active,
    workflow_shadow_mode_enabled,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def _shadow_bypass_loads_settings(*entries: object) -> dict:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_mode"] = True
    settings["driver_assignment"]["shadow_bypass_loads"] = list(entries)
    return settings


def test_workflow_shadow_mode_enabled_reads_nested_block() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_mode"] = True
    assert workflow_shadow_mode_enabled(settings, workflow_name="driver_assignment") is True
    assert workflow_shadow_mode_enabled(settings, workflow_name="pod_lifecycle") is False


def test_workflow_shadow_mode_defaults_false() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert workflow_shadow_mode_enabled(settings, workflow_name="driver_assignment") is False


def test_workflow_shadow_active_uses_injected_state_flag() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert workflow_shadow_active(
        settings,
        {"workflow_shadow_mode": True},
        workflow_name="pod_lifecycle",
    ) is True


def test_shadow_metadata_patch() -> None:
    assert shadow_metadata_patch({}) == {}
    assert shadow_metadata_patch({"workflow_shadow_mode": True}) == {
        "workflow_shadow_mode": True
    }


def test_parse_shadow_mail_recipients_valid() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_emails"] = {"to": ["deb@freightx.ai"]}
    recipients = parse_shadow_mail_recipients(settings, workflow_name="driver_assignment")
    assert recipients is not None
    assert recipients.to == ["deb@freightx.ai"]


def test_parse_shadow_mail_recipients_missing_block() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert parse_shadow_mail_recipients(settings, workflow_name="driver_assignment") is None


def test_parse_shadow_mail_recipients_empty_to() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["pod_lifecycle"]["shadow_emails"] = {"to": []}
    assert parse_shadow_mail_recipients(settings, workflow_name="pod_lifecycle") is None


def test_parse_shadow_mail_recipients_invalid() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_emails"] = {"cc": ["only-cc@example.com"]}
    assert parse_shadow_mail_recipients(settings, workflow_name="driver_assignment") is None


def test_shadow_mail_metadata_patch() -> None:
    recipients = EmailRecipients(to=["deb@freightx.ai"])
    assert shadow_mail_metadata_patch(redirected=True, recipients=recipients) == {
        "shadow_mail_redirect": True,
        "shadow_mail_to": ["deb@freightx.ai"],
    }
    assert shadow_mail_metadata_patch(redirected=False, recipients=recipients) == {}


def test_parse_shadow_bypass_loads_valid_entries() -> None:
    settings = _shadow_bypass_loads_settings(
        {"load_id": "62369", "shipment_id": "1000324868"},
        {"load_id": "61913", "shipment_id": "1000315335"},
    )
    entries = parse_shadow_bypass_loads(settings, workflow_name="driver_assignment")
    assert entries == (
        ShadowBypassLoadEntry(load_id="62369", shipment_id="1000324868"),
        ShadowBypassLoadEntry(load_id="61913", shipment_id="1000315335"),
    )


def test_parse_shadow_bypass_loads_reads_legacy_shadow_live_loads_key() -> None:
    settings = minimal_t3ra_tenant_settings()
    settings["driver_assignment"]["shadow_mode"] = True
    settings["driver_assignment"]["shadow_live_loads"] = [{"load_id": "62369"}]
    entries = parse_shadow_bypass_loads(settings, workflow_name="driver_assignment")
    assert entries == (ShadowBypassLoadEntry(load_id="62369", shipment_id=None),)


def test_parse_shadow_bypass_loads_skips_invalid_entries() -> None:
    settings = _shadow_bypass_loads_settings({}, "bad", {"load_id": "62369"})
    entries = parse_shadow_bypass_loads(settings, workflow_name="driver_assignment")
    assert entries == (ShadowBypassLoadEntry(load_id="62369", shipment_id=None),)


def test_parse_shadow_bypass_loads_missing_block() -> None:
    settings = minimal_t3ra_tenant_settings()
    assert parse_shadow_bypass_loads(settings, workflow_name="driver_assignment") == ()


def test_load_in_shadow_bypass_allowlist_matches_load_id() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert load_in_shadow_bypass_allowlist(
        settings,
        {"load_id": "62369"},
        workflow_name="driver_assignment",
    ) is True


def test_load_in_shadow_bypass_allowlist_matches_shipment_id_only() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert load_in_shadow_bypass_allowlist(
        settings,
        {"shipment_id": "1000324868"},
        workflow_name="driver_assignment",
    ) is True


def test_load_in_shadow_bypass_allowlist_second_entry_matches() -> None:
    settings = _shadow_bypass_loads_settings(
        {"load_id": "62369", "shipment_id": "1000324868"},
        {"load_id": "61913", "shipment_id": "1000315335"},
    )
    assert load_in_shadow_bypass_allowlist(
        settings,
        {"shipment_id": "1000315335"},
        workflow_name="driver_assignment",
    ) is True


def test_load_in_shadow_bypass_allowlist_no_match() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert load_in_shadow_bypass_allowlist(
        settings,
        {"load_id": "99999", "shipment_id": "111"},
        workflow_name="driver_assignment",
    ) is False


def test_workflow_shadow_active_allowlisted_load_bypasses_shadow() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert workflow_shadow_active(
        settings,
        {"workflow_shadow_mode": True, "load_id": "62369"},
        workflow_name="driver_assignment",
    ) is False


def test_workflow_shadow_active_non_allowlisted_stays_shadow() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert workflow_shadow_active(
        settings,
        {"load_id": "99999", "shipment_id": "111"},
        workflow_name="driver_assignment",
    ) is True


def test_shadow_metadata_patch_empty_for_allowlisted_live_run() -> None:
    settings = _shadow_bypass_loads_settings({"load_id": "62369", "shipment_id": "1000324868"})
    assert shadow_metadata_patch(
        {
            "workflow_shadow_mode": True,
            "workflow_name": "driver_assignment",
            "tenant_settings": settings,
            "load_id": "62369",
        }
    ) == {}
