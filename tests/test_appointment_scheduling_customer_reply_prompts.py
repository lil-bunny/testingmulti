"""Tests for appointment scheduling customer reply prompt resolution."""

from __future__ import annotations

from app.services.prompt_service import resolve_appointment_scheduling_customer_reply_prompts


def test_resolve_without_tenant_ref_loads_json_fallback() -> None:
    thread = "email 1 [outbound]\nPlease set delivery 04/03/2026\nemail 2 [inbound]\nPls do it on 5PM"
    rendered, metadata = resolve_appointment_scheduling_customer_reply_prompts(
        None,
        {"thread_text": thread},
    )
    assert "decision" in rendered.system
    assert "accepted" in rendered.system
    assert thread in rendered.user
    assert "Pls do it on 5PM" in rendered.user
    assert "please confirm" in rendered.user.lower()
    assert "Sent Items and Inbox" in rendered.user
    assert metadata.source == "fallback"
    assert metadata.tenant_prompt_ref == "appt-reply"
