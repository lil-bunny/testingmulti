"""Tests for attachment classifier migration onto traced ``chat_vision_json``."""

from __future__ import annotations

import io

from PIL import Image

from app.domain.prompt_step_keys import POD_ATTACHMENT_CLASSIFIER
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.attachment_normalizer import AttachmentNormalizerService
from app.tools import llm_client
from app.tools.llm_client import LLMClientError
from tests.fixtures.t3ra_tenant_settings import T3RA_PROMPTS

_CLASSIFIER_RENDERED = RenderedPrompt(
    system="Classify logistics document validity.",
    user="You are a logistics document classifier.",
)
_CLASSIFIER_META = PromptLoadMetadata(
    source="fallback",
    tenant_prompt_ref="pod-attachment-classifier:staging",
)


def _large_png_bytes() -> bytes:
    img = Image.new("RGB", (120, 120), color=(40, 80, 120))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    data = buf.getvalue()
    while len(data) < 11 * 1024:
        data += b"\x00"
    return data


def _stub_classifier_prompts(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.attachment_normalizer.resolve_pod_attachment_classifier_prompts",
        lambda tenant_settings: (_CLASSIFIER_RENDERED, _CLASSIFIER_META),
    )


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
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {
        "execution_id": "exec-1",
        "workflow_lifecycle_id": "wl-1",
        "tenant_slug": "t3ra",
        "shipment_id": "SHIP-1",
        "tenant_settings": {"prompts": T3RA_PROMPTS},
    }
    result = svc._classify_image(png, attachment_id="att-1")

    assert result["is_valid_document"] is True
    assert result["confidence"] == 0.91
    assert result["reasoning"] == "signed POD"
    assert result["detected_document_type"] == "POD"
    assert result["prefiltered"] is False
    assert captured["system_prompt"] == _CLASSIFIER_RENDERED.system
    assert captured["user_prompt"] == _CLASSIFIER_RENDERED.user
    assert captured["image_jpeg_bytes"] == png
    assert captured["kwargs"]["model"] == "classifier-model"
    assert captured["kwargs"]["image_mime_type"] == "image/png"
    assert captured["kwargs"]["temperature"] == 0.1
    assert captured["kwargs"]["max_tokens"] == 150
    assert "timeout_s" not in captured["kwargs"]  # uses LLM_REQUEST_TIMEOUT default
    meta = captured["kwargs"]["metadata"]
    assert meta["execution_id"] == "exec-1"
    assert meta["workflow_lifecycle_id"] == "wl-1"
    assert meta["thread_id"] == "wl-1"
    assert meta["attachment_id"] == "att-1"
    assert meta["step_key"] == "pod_attachment_classifier"
    assert captured["kwargs"]["tags"] == ["pod_attachment_classifier"]
    prompt_trace = captured["kwargs"]["prompt_trace"]
    assert prompt_trace.prompt_step_key == POD_ATTACHMENT_CLASSIFIER
    assert prompt_trace.tenant_prompt_ref == "pod-attachment-classifier:staging"


def test_classify_image_omits_thread_id_without_lifecycle(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    def fake_chat_vision_json(system_prompt, user_prompt, image_jpeg_bytes, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "doc",
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
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {
        "execution_id": "exec-only",
        "tenant_slug": "t3ra",
        "tenant_settings": {"prompts": T3RA_PROMPTS},
    }
    svc._classify_image(png, attachment_id="att-1")

    meta = captured["kwargs"]["metadata"]
    assert meta["execution_id"] == "exec-only"
    assert "thread_id" not in meta
    assert "workflow_lifecycle_id" not in meta


def test_classify_image_loads_hub_prompt_when_tenant_ref_configured(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    def fake_chat_vision_json(system_prompt, user_prompt, image_jpeg_bytes, **kwargs):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["kwargs"] = kwargs
        return {
            "is_valid_document": True,
            "confidence": 0.88,
            "reasoning": "POD photo",
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
        "app.services.attachment_normalizer.resolve_pod_attachment_classifier_prompts",
        lambda tenant_settings: (
            RenderedPrompt(system="hub-sys", user="hub-usr"),
            PromptLoadMetadata(
                source="hub",
                tenant_prompt_ref="pod-attachment-classifier:staging",
                commit_hash="abc123",
            ),
        ),
    )

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {
        "execution_id": "exec-1",
        "tenant_settings": {
            "prompts": {
                "pod_lifecycle": {
                    "attachment_classifier": "pod-attachment-classifier:staging",
                }
            }
        },
    }
    result = svc._classify_image(png, attachment_id="att-hub")

    assert result["is_valid_document"] is True
    assert captured["system_prompt"] == "hub-sys"
    assert captured["user_prompt"] == "hub-usr"
    assert captured["kwargs"]["prompt_trace"].tenant_prompt_ref == (
        "pod-attachment-classifier:staging"
    )


def test_classify_image_fail_closed_on_llm_error(monkeypatch):
    png = _large_png_bytes()

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.chat_vision_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(LLMClientError("boom")),
    )
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {"tenant_settings": {"prompts": T3RA_PROMPTS}}
    result = svc._classify_image(png, attachment_id="att-err")

    assert result["is_valid_document"] is False
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


def test_llm_trace_inputs_dedupes_prompt_fields():
    shaped = llm_client._llm_trace_inputs(
        {
            "system_prompt": "sys",
            "user_prompt": "user text",
            "temperature": 0.1,
            "timeout_s": 60.0,
            "model": "m1",
            "max_tokens": 150,
            "image_jpeg_bytes": b"\x89PNG\r\n\x1a\n" + b"x" * 20,
            "image_mime_type": "image/png",
        }
    )
    assert "system_prompt" not in shaped
    assert "user_prompt" not in shaped
    assert shaped["messages"][0] == {"role": "system", "content": "sys"}
    assert shaped["messages"][1]["role"] == "user"
    assert isinstance(shaped["messages"][1]["content"], list)
    assert shaped["image"]["mime_type"] == "image/png"


def test_merge_langsmith_extra_keeps_minimal_metadata():
    extra = llm_client._merge_langsmith_extra(
        prompt_trace=None,
        metadata={
            "execution_id": "exec-1",
            "workflow_lifecycle_id": "wl-1",
            "empty": "",
            "none": None,
        },
        tags=["pod_attachment_classifier", ""],
    )
    assert extra == {
        "metadata": {
            "execution_id": "exec-1",
            "workflow_lifecycle_id": "wl-1",
        },
        "tags": ["pod_attachment_classifier"],
    }


def test_normalize_from_bytes_forwards_trace_metadata(monkeypatch):
    png = _large_png_bytes()
    seen: dict = {}

    from app.services.attachment_normalizer import _InMemoryAttachmentNormalizer

    def tracking_normalize(self, refs, shipment_number=None, **kwargs):
        seen["trace_metadata"] = dict(getattr(self, "_trace_metadata", {}) or {})
        return {
            "success": True,
            "pod_merged_pdf_object_key": None,
            "source_attachment_ids": [],
            "classification_results": [],
            "classification_by_attachment_id": {},
            "rejected": [],
            "source_attachments_cleanup": {"rejected": [], "valid_source": []},
        }

    monkeypatch.setattr(_InMemoryAttachmentNormalizer, "normalize", tracking_normalize)

    svc = AttachmentNormalizerService()
    svc.normalize_from_bytes(
        {"att-1": png},
        shipment_number="SHIP-1",
        upload_merged=False,
        trace_metadata={"execution_id": "exec-2", "tenant_slug": "t3ra"},
    )
    assert seen["trace_metadata"] == {
        "execution_id": "exec-2",
        "tenant_slug": "t3ra",
    }
