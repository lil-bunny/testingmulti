"""Tests for ``assess_attachments`` and prior-classification skip in ``normalize``."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from app.core.config import settings
from app.services.attachment_normalizer import AttachmentNormalizerService


def _large_png_bytes() -> bytes:
    img = Image.new("RGB", (120, 120), color=(40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    data = buf.getvalue()
    while len(data) < 11 * 1024:
        data += b"\x00"
    return data


def test_assess_attachments_valid_image_without_upload(monkeypatch):
    png = _large_png_bytes()
    classify_calls: list[bytes] = []

    def fake_classify(self, image_bytes: bytes):
        classify_calls.append(image_bytes)
        return {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "delivery confirmation",
            "detected_document_type": "pod",
        }

    monkeypatch.setattr(
        AttachmentNormalizerService,
        "_classify_image",
        fake_classify,
    )

    svc = AttachmentNormalizerService()
    result = svc.assess_attachments(
        {"att-1": png},
        shipment_number="SHIP-1",
    )

    assert result["success"] is True
    assert result.get("assess_only") is True
    assert result.get("pod_merged_pdf_object_key") is None
    assert len(classify_calls) == 1
    by_id = result.get("classification_by_attachment_id") or {}
    assert "att-1" in by_id
    assert by_id["att-1"]["is_valid_document"] is True


def test_assess_attachments_rejects_invalid_image():
    png = _large_png_bytes()
    svc = AttachmentNormalizerService()

    with patch.object(
        svc,
        "_classify_image",
        return_value={
            "is_valid_document": False,
            "confidence": 0.6,
            "reasoning": "screenshot",
        },
    ):
        result = svc.assess_attachments({"att-bad": png}, shipment_number="SHIP-2")

    assert result["success"] is False
    assert result.get("error") == "rejected_by_classifier"


def test_assess_attachments_pdf_skips_classifier(monkeypatch):
    pdf = b"%PDF-1.4 minimal pod"
    classify = MagicMock()
    monkeypatch.setattr(AttachmentNormalizerService, "_classify_image", classify)

    svc = AttachmentNormalizerService()
    result = svc.assess_attachments({"att-pdf": pdf}, shipment_number="SHIP-3")

    classify.assert_not_called()
    assert result["success"] is True


def test_normalize_reuses_prior_classification_skips_llm(monkeypatch):
    png = _large_png_bytes()
    ship = "SHIP-4"
    att_id = "att-prior"
    ref = (
        f"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_{att_id}_{ship}.png"
    )

    classify = MagicMock()
    monkeypatch.setattr(AttachmentNormalizerService, "_classify_image", classify)

    uploaded: list[str] = []

    def fake_upload(**kwargs):
        uploaded.append(kwargs.get("filename") or "")
        return {
            "success": True,
            "object_key": f"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_merged.pdf",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.bucket.upload_file",
        fake_upload,
    )

    def fake_download(self, attachment_ref: str):
        if attachment_ref == ref:
            return png
        return None

    monkeypatch.setattr(AttachmentNormalizerService, "_download", fake_download)
    monkeypatch.setattr(
        AttachmentNormalizerService,
        "_merge_attachments",
        lambda self, pdfs, images: b"%PDF-1.4 merged",
    )

    prior = {
        att_id: {
            "is_valid_document": True,
            "confidence": 0.88,
            "reasoning": "from gate",
        }
    }

    svc = AttachmentNormalizerService()
    result = svc.normalize(
        [ref],
        shipment_number=ship,
        prior_classification_by_attachment_id=prior,
    )

    classify.assert_not_called()
    cls_rows = result.get("classification_results") or []
    assert cls_rows
    assert cls_rows[0].get("from_ingress_gate") is True
    assert result["success"] is True
