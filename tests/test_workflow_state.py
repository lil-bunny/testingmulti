"""Tests for workflow state payload accessors."""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.state import tenant_slug_from_payload, workflow_state_data
from app.workflows.nodes.turvo import turvo_call_kwargs


def test_workflow_state_data_from_state_and_missing() -> None:
    state = SimpleNamespace(data={"tenant_slug": "t3ra"})
    assert workflow_state_data(state) == {"tenant_slug": "t3ra"}
    assert workflow_state_data(SimpleNamespace()) == {}


def test_tenant_slug_from_payload() -> None:
    assert tenant_slug_from_payload({"tenant_slug": "t3ra"}) == "t3ra"
    assert tenant_slug_from_payload({"tenant_slug": "  t3ra  "}) == "t3ra"
    assert tenant_slug_from_payload({}) is None
    assert tenant_slug_from_payload({"tenant_slug": "   "}) is None


def test_turvo_call_kwargs() -> None:
    assert turvo_call_kwargs({"tenant_slug": "t3ra"}) == {"tenant_slug": "t3ra"}
    state = SimpleNamespace(data={"tenant_slug": "t3ra"})
    assert turvo_call_kwargs(state) == {"tenant_slug": "t3ra"}
