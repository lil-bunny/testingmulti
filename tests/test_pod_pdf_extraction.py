"""Tests for direct-PDF POD extraction (single ``chat_pdf_json`` call)."""

from __future__ import annotations

from app.integrations.langsmith import RenderedPrompt
from app.integrations.langsmith.types import PromptLoadMetadata
from app.services.pod_lifecycle import extraction as pod_extraction


def _fake_pdf_prompts(tenant_settings=None):
    return (
        RenderedPrompt(system="sys", user="user"),
        PromptLoadMetadata(source="fallback", tenant_prompt_ref="pod-pdf-extraction:staging"),
    )


def test_extract_from_pdf_path_uses_page_evidence_and_ignores_reconciled(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    llm_response = {
        "document_summary": {"page_count": 2, "page_types_seen": ["BILL_OF_LADING"], "notes": "ok"},
        "pages": [
            {"page_number": 1, "page_type": "BILL_OF_LADING", "fields": []},
            {"page_number": 2, "page_type": "LUMPER_RECEIPT", "fields": []},
        ],
        "reconciled": {
            "fields": [
                {"key": "carrier_name", "value": "Bajwa Truckers", "confidence": 90},
                {"key": "po_number", "value": "PO1, PO2", "confidence": 80},
                {"key": "po_number", "value": "PO2", "confidence": 70},
            ],
            "proof_of_receipt": {
                "has_receiver_signature": True,
                "receiver_signature_location": "Consignee Box",
                "has_stamp": False,
                "delivery_confirmation_reasoning": "Signed by receiver",
            },
            "stop_times": [
                {
                    "pickup_checkin_time": "2026-02-06T07:34:49Z",
                    "pickup_checkout_time": "",
                    "delivery_checkin_time": "",
                    "delivery_checkout_time": "",
                }
            ],
            "delivery_confirmed": True,
        },
    }

    monkeypatch.setattr(pod_extraction, "resolve_pod_pdf_prompts", _fake_pdf_prompts)
    monkeypatch.setattr(pod_extraction, "pdf_page_count", lambda _b: 2)
    monkeypatch.setattr(pod_extraction, "chat_pdf_json", lambda *a, **k: llm_response)

    page_details, final_pod_data, validation_issues, reconciliation_log, raw_response = (
        pod_extraction.extract_from_pdf_path(str(pdf_path))
    )

    assert len(page_details) == 2
    assert [p["page_number"] for p in page_details] == [1, 2]
    assert page_details[0]["extracted_data"]["page_type"] == "BILL_OF_LADING"
    assert final_pod_data == {}
    assert validation_issues == []
    assert reconciliation_log == {}
    assert raw_response == llm_response


def test_extract_from_pdf_path_requires_page_evidence(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    llm_response = {
        "pages": [],
        "reconciled": {
            "fields": [
                {"key": "carrier_name", "value": "T3RA Logistics", "confidence": 95},
            ],
            "proof_of_receipt": {"has_receiver_signature": False, "has_stamp": False},
            "stop_times": [],
        },
    }

    monkeypatch.setattr(pod_extraction, "resolve_pod_pdf_prompts", _fake_pdf_prompts)
    monkeypatch.setattr(pod_extraction, "pdf_page_count", lambda _b: 1)
    monkeypatch.setattr(pod_extraction, "chat_pdf_json", lambda *a, **k: llm_response)

    _page_details, final_pod_data, validation_issues, _log, _raw = (
        pod_extraction.extract_from_pdf_path(str(pdf_path), broker_name="T3RA Logistics")
    )

    assert final_pod_data == {}
    assert validation_issues == []


def test_extract_from_pdf_path_handles_missing_page_evidence(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(pod_extraction, "resolve_pod_pdf_prompts", _fake_pdf_prompts)
    monkeypatch.setattr(pod_extraction, "pdf_page_count", lambda _b: 1)
    monkeypatch.setattr(pod_extraction, "chat_pdf_json", lambda *a, **k: {"pages": []})

    page_details, final_pod_data, validation_issues, _log, raw_response = (
        pod_extraction.extract_from_pdf_path(str(pdf_path))
    )

    assert len(page_details) == 1
    assert page_details[0].get("error")
    assert final_pod_data == {}
    assert validation_issues == []
    assert raw_response == {"pages": []}


def test_extract_from_pdf_path_raises_when_too_many_bytes(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4" + b"x" * 100)

    monkeypatch.setattr(pod_extraction.settings, "POD_PDF_MAX_BYTES", 10)

    import pytest

    with pytest.raises(pod_extraction.PdfTooLargeError):
        pod_extraction.extract_from_pdf_path(str(pdf_path))


def test_extract_from_pdf_path_raises_when_too_many_pages(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(pod_extraction, "pdf_page_count", lambda _b: 5)
    monkeypatch.setattr(pod_extraction.settings, "POD_PDF_MAX_PAGES", 2)

    import pytest

    with pytest.raises(pod_extraction.PdfTooLargeError):
        pod_extraction.extract_from_pdf_path(str(pdf_path))


def test_build_page_results_ignores_non_dict_entries():
    wrapped = pod_extraction.build_page_results(
        [{"page_number": 1}, "not-a-dict", None], "load-1"
    )
    assert len(wrapped) == 1
    assert wrapped[0]["load_id"] == "load-1"


