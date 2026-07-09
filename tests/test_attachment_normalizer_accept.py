"""Unit tests for strict ``_accept_image`` (``is_valid_document`` only)."""

from __future__ import annotations

from app.services.attachment_normalizer import AttachmentNormalizerService


def test_accept_image_true_when_is_valid_document_true():
    assert AttachmentNormalizerService._accept_image(
        {"is_valid_document": True, "confidence": 0.3}
    )


def test_accept_image_false_when_is_valid_document_false_even_low_confidence():
    assert not AttachmentNormalizerService._accept_image(
        {"is_valid_document": False, "confidence": 0.6}
    )


def test_accept_image_false_when_is_valid_document_missing():
    assert not AttachmentNormalizerService._accept_image({"confidence": 0.95})


def test_accept_image_false_when_is_valid_document_false_high_confidence():
    assert not AttachmentNormalizerService._accept_image(
        {"is_valid_document": False, "confidence": 0.99}
    )
