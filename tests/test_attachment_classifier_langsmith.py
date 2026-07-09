"""Tests for attachment classifier migration onto traced ``chat_vision_json``."""

from __future__ import annotations

import io

from PIL import Image

from app.services.attachment_normalizer import (
    IMAGE_CLASSIFIER_SYSTEM_PROMPT,
    IMAGE_CLASSIFIER_USER_PROMPT,
    AttachmentNormalizerService,
)
from app.tools.llm_client import LLMClientError


def _large_png_bytes() -> bytes:
    img = Image.new("RGB", (120, 120), color=(40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    data = buf.getvalue()
    while len(data) < 11 * 1024:
        data += b"\x00"
    return data


def test_classify_image_uses_chat_vision_json(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    def fake_chat_vision_json(
        system_prompt,
        user_prompt,
        image_jpeg_bytes,
        **kwargs,
    ):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["image_jpeg_bytes"] = image_jpeg_bytes
        captured["kwargs"] = kwargs
        return {
            "is_valid_document": True,
            "confidence": 0.91,
            "reasoning": "signed POD",
            "detected_document_type": "POD",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.chat_vision_json",
        fake_chat_vision_json,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.ATTACHMENT_CLASSIFIER_MODEL",
        "classifier-model",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_MODEL",
        "default-model",
    )

    svc = AttachmentNormalizerService()
    result = svc._classify_image(png, attachment_id="att-1")

    assert result["is_valid_document"] is True
    assert result["confidence"] == 0.91
    assert result["reasoning"] == "signed POD"
    assert result["detected_document_type"] == "POD"
    assert result["prefiltered"] is False
    assert captured["system_prompt"] == IMAGE_CLASSIFIER_SYSTEM_PROMPT
    assert captured["user_prompt"] == IMAGE_CLASSIFIER_USER_PROMPT
    assert captured["image_jpeg_bytes"] == png
    assert captured["kwargs"]["model"] == "classifier-model"
    assert captured["kwargs"]["image_mime_type"] == "image/png"
    assert captured["kwargs"]["temperature"] == 0.1
    assert captured["kwargs"]["max_tokens"] == 150


def test_classify_image_fail_open_on_llm_error(monkeypatch):
    png = _large_png_bytes()

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.chat_vision_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(LLMClientError("boom")),
    )

    svc = AttachmentNormalizerService()
    result = svc._classify_image(png, attachment_id="att-err")

    assert result["is_valid_document"] is True
    assert result["confidence"] == 0.0
    assert "classification_error" in result["reasoning"]


def test_classify_image_skips_without_api_key(monkeypatch):
    png = _large_png_bytes()
    called = {"n": 0}

    def fake_chat_vision_json(*args, **kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        None,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.chat_vision_json",
        fake_chat_vision_json,
    )

    svc = AttachmentNormalizerService()
    result = svc._classify_image(png)

    assert called["n"] == 0
    assert result["is_valid_document"] is True
    assert result["reasoning"] == "no_classifier_api_key_configured"


def test_chat_vision_json_passes_model_override(monkeypatch):
    from app.tools import llm_client

    seen: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"is_valid_document": true, "confidence": 0.8, '
                                '"reasoning": "ok", "detected_document_type": "BOL"}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, endpoint, headers=None, json=None):
            seen["json"] = json
            return FakeResponse()

    monkeypatch.setattr(llm_client.settings, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "k")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "default-model")
    monkeypatch.setattr(llm_client.httpx, "Client", FakeClient)
    monkeypatch.setattr(llm_client, "get_current_run_tree", lambda: None)

    out = llm_client.chat_vision_json(
        "sys",
        "user",
        b"\xff\xd8\xfffake",
        model="override-model",
        image_mime_type="image/jpeg",
        max_tokens=150,
        temperature=0.1,
    )

    assert out["is_valid_document"] is True
    assert seen["json"]["model"] == "override-model"
    assert seen["json"]["max_tokens"] == 150
