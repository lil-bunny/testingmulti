"""Unit tests for modality-aware LLM client helpers."""

from __future__ import annotations

import base64

import pytest
from openai import APITimeoutError

from app.tools import llm_client
from app.tools.llm_credentials import LLMCredentials
from app.tools.llm_client import LLMClientError

_CREDENTIALS = LLMCredentials(base_url="https://llm.example", api_key="k")


def _patch_llm_settings(monkeypatch) -> None:
    monkeypatch.setattr(llm_client.settings, "LLM_CHAT_MODEL", "chat")
    monkeypatch.setattr(llm_client.settings, "LLM_VISION_MODEL", "vision")
    monkeypatch.setattr(llm_client.settings, "LLM_PDF_MODEL", "pdf")
    monkeypatch.setattr(llm_client, "get_current_run_tree", lambda: None)


def _install_fake_openai(monkeypatch, *, create_side_effect=None):
    seen: dict = {}

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            seen["kwargs"] = kwargs
            if create_side_effect is not None:
                raise create_side_effect
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

    monkeypatch.setattr(llm_client, "AsyncOpenAI", FakeAsyncOpenAI)
    return seen


@pytest.mark.parametrize(
    ("modality", "expected_model", "call_fn"),
    [
        (
            "chat",
            "chat",
            lambda: llm_client.chat_json("sys", "user", credentials=_CREDENTIALS),
        ),
        (
            "vision",
            "vision",
            lambda: llm_client.chat_vision_json(
                "sys", "user", b"\xff\xd8\xfffake", credentials=_CREDENTIALS
            ),
        ),
        (
            "pdf",
            "pdf",
            lambda: llm_client.chat_pdf_json(
                "sys", "user", b"%PDF-1.4", credentials=_CREDENTIALS
            ),
        ),
    ],
)
def test_modality_defaults_resolve_gateway_aliases(
    monkeypatch,
    modality,
    expected_model,
    call_fn,
):
    _patch_llm_settings(monkeypatch)
    seen = _install_fake_openai(monkeypatch)

    out = call_fn()

    assert out == {"ok": True}
    assert seen["kwargs"]["model"] == expected_model


def test_explicit_model_override(monkeypatch):
    _patch_llm_settings(monkeypatch)
    seen = _install_fake_openai(monkeypatch)

    llm_client.chat_json(
        "sys", "user", credentials=_CREDENTIALS, model="custom-model"
    )

    assert seen["kwargs"]["model"] == "custom-model"


def test_resolve_model_raises_when_modality_setting_blank(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "LLM_CHAT_MODEL", "")

    with pytest.raises(LLMClientError, match="LLM config missing"):
        llm_client._resolve_model(None, modality="chat")


def test_chat_pdf_json_sends_image_url_pdf_data_url(monkeypatch):
    _patch_llm_settings(monkeypatch)
    seen = _install_fake_openai(monkeypatch)
    pdf_bytes = b"%PDF-1.4 fake"

    llm_client.chat_pdf_json(
        "sys",
        "extract fields",
        pdf_bytes,
        credentials=_CREDENTIALS,
        filename="pod.pdf",
    )

    kwargs = seen["kwargs"]
    user_content = kwargs["messages"][1]["content"]
    assert kwargs["model"] == "pdf"
    assert user_content[0] == {"type": "text", "text": "extract fields"}
    pdf_part = user_content[1]
    assert pdf_part["type"] == "image_url"
    expected_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    assert pdf_part["image_url"]["url"] == f"data:application/pdf;base64,{expected_b64}"


def test_llm_trace_inputs_omits_pdf_base64():
    shaped = llm_client._llm_trace_inputs(
        {
            "system_prompt": "sys",
            "user_prompt": "user text",
            "temperature": 0.1,
            "timeout_s": 60.0,
            "model": "pdf",
            "pdf_bytes": b"%PDF-1.4" + b"x" * 20,
            "pdf_filename": "pod.pdf",
        }
    )
    assert shaped["pdf"] == {"filename": "pod.pdf", "bytes": 28, "present": True}
    url = shaped["messages"][1]["content"][1]["image_url"]["url"]
    assert "omitted 28 bytes" in url
    assert "%PDF" not in url


def test_chat_json_raises_llm_client_error_on_timeout(monkeypatch):
    _patch_llm_settings(monkeypatch)
    _install_fake_openai(monkeypatch, create_side_effect=APITimeoutError("timed out"))

    with pytest.raises(LLMClientError, match="Failed LLM chat_json call"):
        llm_client.chat_json("sys", "user", credentials=_CREDENTIALS)
