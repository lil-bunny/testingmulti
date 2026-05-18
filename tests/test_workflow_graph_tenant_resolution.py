"""Tests for ``resolve_workflow_graph_tenant_id``."""

from __future__ import annotations

import pytest

from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id


class _RepoEmpty:
    def get_slug_for_tenant_uuid(self, _: str):
        return None


class _RepoGelita:
    def get_slug_for_tenant_uuid(self, _: str):
        return "gelita"


class _RepoUnknownSlug:
    def get_slug_for_tenant_uuid(self, _: str):
        return "not_a_graph_tenant_key"


def test_resolve_uses_tenant_slug_when_key_valid() -> None:
    """``tenants.slug`` wins even if webhook_name is not a TENANT_CONFIGS key."""
    out = resolve_workflow_graph_tenant_id(
        data_import_tenant_id="00000000-0000-0000-0000-000000000001",
        webhook_name="something_else",
        tenants_repo=_RepoGelita(),
    )
    assert out == "gelita"


def test_resolve_unknown_slug_falls_back_to_webhook_name() -> None:
    out = resolve_workflow_graph_tenant_id(
        data_import_tenant_id="00000000-0000-0000-0000-000000000002",
        webhook_name="gelita",
        tenants_repo=_RepoUnknownSlug(),
    )
    assert out == "gelita"


def test_resolve_default_t3ra_when_no_match() -> None:
    out = resolve_workflow_graph_tenant_id(
        data_import_tenant_id="00000000-0000-0000-0000-000000000003",
        webhook_name="unmapped_vendor",
        tenants_repo=_RepoEmpty(),
    )
    assert out == "t3ra"


@pytest.mark.parametrize("blank", ["", "   "])
def test_resolve_webhook_name_trim(blank: str) -> None:
    out = resolve_workflow_graph_tenant_id(
        data_import_tenant_id="00000000-0000-0000-0000-000000000004",
        webhook_name=blank,
        tenants_repo=_RepoEmpty(),
    )
    assert out == "t3ra"
