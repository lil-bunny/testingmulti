"""Tests for thread-history inline attachment filtering (CID-based).

Uses real Unipile webhook payloads (Outlook and Gmail) as fixtures to verify
that inline images from quoted thread history are correctly identified and
filtered out, while inline images in the new/original message are kept.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.unipile_email_attachments import (
    extract_cids_from_original_html,
    is_thread_history_inline,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def outlook_payload() -> dict:
    path = FIXTURES_DIR / "outlook.unipile.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    if "input" in state:
        return state["input"]["data"]
    return state


@pytest.fixture
def gmail_payload() -> dict:
    path = FIXTURES_DIR / "gmail.unipile.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestExtractCidsFromOriginalHtml:
    def test_no_boundaries_returns_all_cids(self):
        html = '<img src="cid:aaa"><img src="cid:bbb">'
        assert extract_cids_from_original_html(html) == {"aaa", "bbb"}

    def test_empty_html(self):
        assert extract_cids_from_original_html("") == set()
        assert extract_cids_from_original_html(None) == set()

    def test_cid_before_gmail_quote_kept(self):
        html = (
            '<div><img src="cid:new_img"></div>'
            '<div class="gmail_quote gmail_quote_container">'
            '<img src="cid:old_img">'
            "</div>"
        )
        assert extract_cids_from_original_html(html) == {"new_img"}

    def test_cid_before_outlook_appendonsend_kept(self):
        html = (
            '<div><img src="cid:new_img"></div>'
            '<div id="appendonsend"></div>'
            '<img src="cid:old_img">'
        )
        assert extract_cids_from_original_html(html) == {"new_img"}

    def test_cid_before_outlook_divRplyFwdMsg_kept(self):
        html = (
            '<div><img src="cid:new_img"></div>'
            '<div id="divRplyFwdMsg">'
            '<img src="cid:old_img">'
            "</div>"
        )
        assert extract_cids_from_original_html(html) == {"new_img"}

    def test_cid_before_hr_kept(self):
        html = (
            '<div><img src="cid:new_img"></div>'
            "<hr>"
            '<img src="cid:old_img">'
        )
        assert extract_cids_from_original_html(html) == {"new_img"}

    def test_earliest_boundary_wins(self):
        html = (
            '<img src="cid:before_all">'
            '<div id="appendonsend"></div>'
            '<img src="cid:between">'
            "<hr>"
            '<img src="cid:after_hr">'
        )
        assert extract_cids_from_original_html(html) == {"before_all"}


class TestIsThreadHistoryInline:
    def test_inline_with_cid_not_in_original(self):
        att = {"inline": True, "cid": "old_cid"}
        assert is_thread_history_inline(att, set()) is True
        assert is_thread_history_inline(att, {"other_cid"}) is True

    def test_inline_with_cid_in_original(self):
        att = {"inline": True, "cid": "my_cid"}
        assert is_thread_history_inline(att, {"my_cid"}) is False

    def test_not_inline_never_skipped(self):
        att = {"inline": False, "cid": "some_cid"}
        assert is_thread_history_inline(att, set()) is False

    def test_no_cid_never_skipped(self):
        att = {"inline": True}
        assert is_thread_history_inline(att, set()) is False

    def test_empty_cid_never_skipped(self):
        att = {"inline": True, "cid": ""}
        assert is_thread_history_inline(att, set()) is False


class TestOutlookWebhookFixture:
    """Outlook: Ratan's reply has no new inlines; all 3 attachments are thread history."""

    def test_original_cids_empty(self, outlook_payload):
        body = outlook_payload.get("body") or ""
        assert extract_cids_from_original_html(body) == set()

    def test_all_attachments_are_thread_history(self, outlook_payload):
        body = outlook_payload.get("body") or ""
        original_cids = extract_cids_from_original_html(body)
        attachments = outlook_payload["attachments"]

        assert len(attachments) == 3
        for att in attachments:
            assert att["inline"] is True
            assert is_thread_history_inline(att, original_cids) is True

    def test_filter_removes_all_thread_history_inlines(self, outlook_payload):
        body = outlook_payload.get("body") or ""
        original_cids = extract_cids_from_original_html(body)
        kept = [
            att for att in outlook_payload["attachments"]
            if not is_thread_history_inline(att, original_cids)
        ]
        assert kept == []


class TestGmailWebhookFixture:
    """Gmail: Axle's reply 'we can accept this' has no new inlines; image is from prior reply."""

    def test_original_cids_empty(self, gmail_payload):
        body = gmail_payload.get("body") or ""
        assert extract_cids_from_original_html(body) == set()

    def test_attachment_is_thread_history(self, gmail_payload):
        body = gmail_payload.get("body") or ""
        original_cids = extract_cids_from_original_html(body)
        attachments = gmail_payload["attachments"]

        assert len(attachments) == 1
        assert attachments[0]["cid"] == "ii_msevgh710"
        assert is_thread_history_inline(attachments[0], original_cids) is True

    def test_filter_removes_thread_history_inline(self, gmail_payload):
        body = gmail_payload.get("body") or ""
        original_cids = extract_cids_from_original_html(body)
        kept = [
            att for att in gmail_payload["attachments"]
            if not is_thread_history_inline(att, original_cids)
        ]
        assert kept == []


class TestNewInlineImageKept:
    """When the sender includes a NEW inline image in their reply, it should NOT be filtered."""

    def test_gmail_new_inline_kept(self):
        html = (
            '<html><body>'
            '<div dir="ltr">Here is the POD <img src="cid:new_pod_123"></div>'
            '<div class="gmail_quote gmail_quote_container">'
            '<blockquote><img src="cid:old_thread_456"></blockquote>'
            '</div></body></html>'
        )
        original_cids = extract_cids_from_original_html(html)
        assert original_cids == {"new_pod_123"}

        att_new = {"inline": True, "cid": "new_pod_123", "name": "pod.jpg"}
        att_old = {"inline": True, "cid": "old_thread_456", "name": "old.jpg"}

        assert is_thread_history_inline(att_new, original_cids) is False
        assert is_thread_history_inline(att_old, original_cids) is True

    def test_outlook_new_inline_kept(self):
        html = (
            '<html><body>'
            '<div class="elementToProof"><img src="cid:new_pod_789"></div>'
            '<div id="appendonsend"></div>'
            '<hr><div id="divRplyFwdMsg"><img src="cid:old_sig_000"></div>'
            '</body></html>'
        )
        original_cids = extract_cids_from_original_html(html)
        assert original_cids == {"new_pod_789"}

        att_new = {"inline": True, "cid": "new_pod_789", "name": "pod.png"}
        att_old = {"inline": True, "cid": "old_sig_000", "name": "sig.png"}

        assert is_thread_history_inline(att_new, original_cids) is False
        assert is_thread_history_inline(att_old, original_cids) is True

    def test_non_inline_attachment_always_kept(self):
        """Regular attachments (PDFs, etc.) should never be filtered regardless of CID."""
        att = {"inline": False, "cid": "whatever", "name": "pod.pdf", "mime": "application/pdf"}
        assert is_thread_history_inline(att, set()) is False
        assert is_thread_history_inline(att, {"whatever"}) is False
