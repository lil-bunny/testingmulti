"""CommunicationsService appointment reply thread merge tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.services.communications.service import CommunicationsService

_TENANT = "00000000-0000-4000-8000-0000000000e1"
_THREAD = "thread-inbound"
_DRAFT_ID = "36ae1bf5-fd32-48aa-934b-634ac863b110"
_INBOUND_ID = "a768df77-c450-44f0-8f34-22945de1bc2a"

_OUTBOUND_AT = datetime(2026, 7, 21, 10, 12, 16, tzinfo=timezone.utc)
_INBOUND_AT = datetime(2026, 7, 21, 10, 15, 48, tzinfo=timezone.utc)


def _draft_row() -> dict:
    return {
        "id": _DRAFT_ID,
        "direction": "outbound",
        "content": "<p>Proposed delivery THURSDAY 04/02/2026</p>",
        "metadata": {"to": ["customer@example.com"], "from": "ops@freightx.ai"},
        "created_at": _OUTBOUND_AT,
    }


def _inbound_row() -> dict:
    return {
        "id": _INBOUND_ID,
        "direction": "inbound",
        "content": "<div>Pls do it on 5PM</div>",
        "metadata": {"from": "customer@example.com", "to": ["ops@freightx.ai"]},
        "created_at": _INBOUND_AT,
    }


def _service(*, thread_rows: list[dict], draft_row: dict | None) -> CommunicationsService:
    repo = MagicMock()
    repo.list_email_thread.return_value = thread_rows
    repo.get_email_by_id.return_value = draft_row
    svc = CommunicationsService(repository=repo)
    svc._tenant_uuid_or_none = lambda _tenant: _TENANT  # type: ignore[method-assign]
    return svc


def test_merge_prepends_draft_when_thread_is_inbound_only() -> None:
    svc = _service(thread_rows=[_inbound_row()], draft_row=_draft_row())
    text, count = svc.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=_DRAFT_ID,
    )
    assert count == 2
    assert "email 1" in text
    assert "email 2" in text
    assert "THURSDAY 04/02/2026" in text
    assert "Pls do it on 5PM" in text
    assert text.index("THURSDAY") < text.index("Pls do it on 5PM")


def test_merge_skips_when_draft_already_in_thread() -> None:
    rows = [_draft_row(), _inbound_row()]
    svc = _service(thread_rows=rows, draft_row=_draft_row())
    text, count = svc.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=_DRAFT_ID,
    )
    assert count == 2
    assert text.count("email 1") == 1
    assert text.count("email 2") == 1


def test_merge_skips_when_thread_already_has_outbound() -> None:
    other_outbound = {
        "id": "other-outbound-id",
        "direction": "outbound",
        "content": "<p>Original outbound in thread</p>",
        "metadata": {"to": ["customer@example.com"]},
        "created_at": _OUTBOUND_AT,
    }
    svc = _service(thread_rows=[other_outbound, _inbound_row()], draft_row=_draft_row())
    text, count = svc.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=_DRAFT_ID,
    )
    assert count == 2
    assert "Original outbound in thread" in text
    assert "THURSDAY 04/02/2026" not in text
    repo = svc._repository
    repo.get_email_by_id.assert_not_called()


def test_thread_only_when_no_draft_id() -> None:
    svc = _service(thread_rows=[_inbound_row()], draft_row=None)
    text, count = svc.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=None,
    )
    assert count == 1
    assert "Pls do it on 5PM" in text
    assert "THURSDAY" not in text


def test_thread_only_when_draft_missing_or_empty() -> None:
    svc = _service(thread_rows=[_inbound_row()], draft_row=None)
    text, count = svc.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=_DRAFT_ID,
    )
    assert count == 1
    assert "Pls do it on 5PM" in text

    empty_draft = {**_draft_row(), "content": "   "}
    svc2 = _service(thread_rows=[_inbound_row()], draft_row=empty_draft)
    text2, count2 = svc2.build_appointment_reply_thread_llm_user_message(
        _TENANT,
        _THREAD,
        draft_communication_id=_DRAFT_ID,
    )
    assert count2 == 1
    assert "Pls do it on 5PM" in text2
