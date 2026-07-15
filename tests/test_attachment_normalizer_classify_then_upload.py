from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

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


def test_stage_accepted_files_writes_image_once_shared_path(tmp_path):
    """Images land once under sources/; merge and vision lists share that path."""
    png = _large_png_bytes()
    merge_paths, vision_paths = AttachmentNormalizerService._stage_accepted_files(
        [],
        [("s3://bucket/pod_att1_SHIP.bin", png)],
        stage_dir=str(tmp_path),
        shipment_number="SHIP",
    )

    assert len(merge_paths) == 1
    assert vision_paths == merge_paths
    staged = Path(merge_paths[0])
    assert staged.is_file()
    assert staged.parent.name == "sources"
    assert not (tmp_path / "vision").exists()
    assert staged.read_bytes() == png


def test_normalize_from_bytes_uploads_merged_pdf_for_valid_image(monkeypatch):
    png = _large_png_bytes()
    upload_calls: list[dict] = []

    def fake_upload(**kwargs):
        upload_calls.append(kwargs)
        return {
            "success": True,
            "object_key": f"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_SHIP.pdf",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.bucket.upload_file",
        fake_upload,
    )
    monkeypatch.setattr(
        AttachmentNormalizerService,
        "_classify_image",
        lambda self, image_bytes, **kwargs: {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "pod photo",
            "detected_document_type": "POD",
        },
    )
    monkeypatch.setattr(
        AttachmentNormalizerService,
        "_merge_attachments",
        lambda self, pdfs, images: b"%PDF-1.4 merged",
    )

    svc = AttachmentNormalizerService()
    result = svc.normalize_from_bytes(
        {"att-valid": png},
        shipment_number="SHIP",
        upload_merged=True,
    )

    assert result["success"] is True
    assert result.get("pod_merged_pdf_object_key")
    assert len(upload_calls) == 1
    assert upload_calls[0]["content_type"] == "application/pdf"


def test_normalize_from_bytes_rejected_image_skips_s3_upload(monkeypatch):
    png = _large_png_bytes()
    upload = MagicMock()
    monkeypatch.setattr("app.services.attachment_normalizer.bucket.upload_file", upload)
    monkeypatch.setattr(
        AttachmentNormalizerService,
        "_classify_image",
        lambda self, image_bytes, **kwargs: {
            "is_valid_document": False,
            "confidence": 0.95,
            "reasoning": "truck photo",
        },
    )

    svc = AttachmentNormalizerService()
    result = svc.normalize_from_bytes(
        {"att-bad": png},
        shipment_number="SHIP",
        upload_merged=True,
    )

    upload.assert_not_called()
    assert result["success"] is False
    assert result.get("pod_merged_pdf_object_key") is None
