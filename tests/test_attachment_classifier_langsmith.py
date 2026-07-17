"""Tests for attachment classifier on traced ``achat_vision_json``."""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import Image

from app.domain.pod_lifecycle.guards import ATTACHMENT_CLASSIFIER_FAILED
from app.domain.prompt_step_keys import POD_ATTACHMENT_CLASSIFIER
from app.integrations.langsmith.types import PromptLoadMetadata, RenderedPrompt
from app.services.attachment_normalizer import (
    AttachmentClassifierFailed,
    AttachmentNormalizerService,
)
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


@pytest.mark.asyncio
async def test_aclassify_image_uses_achat_vision_json(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    async def fake_achat_vision_json(
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
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
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
    result = await svc._aclassify_image(png, attachment_id="att-1")

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


@pytest.mark.asyncio
async def test_aclassify_image_omits_thread_id_without_lifecycle(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    async def fake_achat_vision_json(system_prompt, user_prompt, image_jpeg_bytes, **kwargs):
        captured["kwargs"] = kwargs
        return {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "doc",
            "detected_document_type": "POD",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
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
    await svc._aclassify_image(png, attachment_id="att-1")

    meta = captured["kwargs"]["metadata"]
    assert meta["execution_id"] == "exec-only"
    assert "thread_id" not in meta
    assert "workflow_lifecycle_id" not in meta


@pytest.mark.asyncio
async def test_aclassify_image_loads_hub_prompt_when_tenant_ref_configured(monkeypatch):
    png = _large_png_bytes()
    captured: dict = {}

    async def fake_achat_vision_json(system_prompt, user_prompt, image_jpeg_bytes, **kwargs):
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
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
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
    result = await svc._aclassify_image(png, attachment_id="att-hub")

    assert result["is_valid_document"] is True
    assert captured["system_prompt"] == "hub-sys"
    assert captured["user_prompt"] == "hub-usr"
    assert captured["kwargs"]["prompt_trace"].tenant_prompt_ref == (
        "pod-attachment-classifier:staging"
    )


@pytest.mark.asyncio
async def test_aclassify_image_raises_on_llm_error(monkeypatch):
    png = _large_png_bytes()

    async def boom(*args, **kwargs):
        raise LLMClientError("boom")

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        boom,
    )
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {"tenant_settings": {"prompts": T3RA_PROMPTS}}
    with pytest.raises(AttachmentClassifierFailed):
        await svc._aclassify_image(png, attachment_id="att-err")


@pytest.mark.asyncio
async def test_normalize_async_maps_llm_error_to_classifier_failed(monkeypatch):
    png = _large_png_bytes()

    async def boom(*args, **kwargs):
        raise LLMClientError("boom")

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        boom,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.build_async_llm_client",
        lambda **kwargs: _NullAsyncClientCtx(),
    )
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    svc._trace_metadata = {"tenant_settings": {"prompts": T3RA_PROMPTS}}
    result = await svc.normalize_from_bytes_async(
        {"att-err": png},
        shipment_number="SHIP",
        upload_merged=False,
    )
    assert result["success"] is False
    assert result["error"] == ATTACHMENT_CLASSIFIER_FAILED


@pytest.mark.asyncio
async def test_aclassify_image_skips_without_api_key(monkeypatch):
    png = _large_png_bytes()
    called = {"n": 0}

    async def fake_achat_vision_json(*args, **kwargs):
        called["n"] += 1
        return {}

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        None,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
    )

    svc = AttachmentNormalizerService()
    result = await svc._aclassify_image(png)

    assert called["n"] == 0
    assert result["is_valid_document"] is True
    assert result["reasoning"] == "no_classifier_api_key_configured"


@pytest.mark.asyncio
async def test_classify_images_batch_runs_concurrently(monkeypatch):
    png = _large_png_bytes()
    in_flight = {"n": 0, "max": 0}

    async def fake_achat_vision_json(*args, **kwargs):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        await asyncio.sleep(0.05)
        in_flight["n"] -= 1
        return {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "ok",
            "detected_document_type": "POD",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.ATTACHMENT_CLASSIFIER_CONCURRENCY",
        3,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.build_async_llm_client",
        lambda **kwargs: _NullAsyncClientCtx(),
    )
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    items = [
        (f"ref-{i}", png, f"att-{i}")
        for i in range(3)
    ]
    results = await svc.classify_images_batch(items)
    assert len(results) == 3
    assert in_flight["max"] >= 2


@pytest.mark.asyncio
async def test_aclassify_under_running_loop_does_not_nest_asyncio_run(monkeypatch):
    """Regression: classify must await achat_vision_json, not chat_vision_json/asyncio.run."""
    png = _large_png_bytes()

    async def fake_achat_vision_json(*args, **kwargs):
        # Prove we are already on a running loop (would fail if nested asyncio.run).
        asyncio.get_running_loop()
        return {
            "is_valid_document": True,
            "confidence": 0.9,
            "reasoning": "ok",
            "detected_document_type": "POD",
        }

    monkeypatch.setattr(
        "app.services.attachment_normalizer.settings.LLM_API_KEY",
        "test-key",
    )
    monkeypatch.setattr(
        "app.services.attachment_normalizer.achat_vision_json",
        fake_achat_vision_json,
    )
    _stub_classifier_prompts(monkeypatch)

    svc = AttachmentNormalizerService()
    result = await svc._aclassify_image(png, attachment_id="att-loop")
    assert result["is_valid_document"] is True


def test_chat_vision_json_passes_model_override(monkeypatch):
    seen: dict = {}

    class FakeMessage:
        content = (
            '{"is_valid_document": true, "confidence": 0.8, '
            '"reasoning": "ok", "detected_document_type": "BOL"}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            seen["kwargs"] = kwargs
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            pass

        @property
        def chat(self):
            return FakeChat()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(llm_client.settings, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm_client.settings, "LLM_API_KEY", "k")
    monkeypatch.setattr(llm_client.settings, "LLM_MODEL", "default-model")
    monkeypatch.setattr(llm_client.settings, "LLM_JSON_RESPONSE_MODE", True)
    monkeypatch.setattr(llm_client, "AsyncOpenAI", FakeAsyncOpenAI)
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
    assert seen["kwargs"]["model"] == "override-model"
    assert seen["kwargs"]["max_tokens"] == 150
    assert seen["kwargs"]["response_format"] == {"type": "json_object"}


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

    async def tracking_normalize(self, refs, shipment_number=None, **kwargs):
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

    monkeypatch.setattr(
        _InMemoryAttachmentNormalizer,
        "normalize_async",
        tracking_normalize,
    )

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


class _NullAsyncClientCtx:
    """Async context manager yielding None (classify uses injected client=None path)."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return None
