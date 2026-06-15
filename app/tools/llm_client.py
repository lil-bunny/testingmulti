import base64
import json
from typing import Any

import httpx
from langsmith import traceable

from app.core.config import settings
from app.integrations.langsmith.types import PromptTraceMetadata


class LLMClientError(Exception):
    pass


def _extract_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    return json.loads(text)


def _llm_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    traced: dict[str, Any] = {
        "system_prompt": inputs.get("system_prompt"),
        "user_prompt": inputs.get("user_prompt"),
        "temperature": inputs.get("temperature"),
        "timeout_s": inputs.get("timeout_s"),
    }
    if "max_tokens" in inputs:
        traced["max_tokens"] = inputs["max_tokens"]
    image = inputs.get("image_jpeg_bytes")
    if isinstance(image, (bytes, bytearray)):
        traced["image_jpeg_bytes"] = f"{len(image)} bytes"
    return traced


@traceable(run_type="llm", name="chat_json", process_inputs=_llm_trace_inputs)
def _chat_json_impl(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float,
    timeout_s: float,
) -> dict:
    base_url = settings.LLM_BASE_URL
    model = settings.LLM_MODEL
    api_key = settings.LLM_API_KEY
    if not base_url or not model or not api_key:
        raise LLMClientError("LLM config missing (base_url/model/api_key)")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        return _extract_json(content)
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise LLMClientError("Failed LLM chat_json call") from exc


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout_s: float = 60.0,
    prompt_trace: PromptTraceMetadata | None = None,
) -> dict:
    """OpenAI-compatible chat completion; optional prompt trace metadata on LangSmith span."""
    langsmith_extra: dict[str, Any] | None = None
    if prompt_trace is not None:
        langsmith_extra = {"metadata": prompt_trace.to_langsmith_metadata()}
    return _chat_json_impl(
        system_prompt,
        user_prompt,
        temperature=temperature,
        timeout_s=timeout_s,
        langsmith_extra=langsmith_extra,
    )


@traceable(run_type="llm", name="chat_vision_json", process_inputs=_llm_trace_inputs)
def _chat_vision_json_impl(
    system_prompt: str,
    user_prompt: str,
    image_jpeg_bytes: bytes,
    *,
    temperature: float,
    timeout_s: float,
    max_tokens: int | None = None,
) -> dict:
    base_url = settings.LLM_BASE_URL
    model = settings.LLM_MODEL
    api_key = settings.LLM_API_KEY
    if not base_url or not model or not api_key:
        raise LLMClientError("LLM config missing (base_url/model/api_key)")

    b64 = base64.b64encode(image_jpeg_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        return _extract_json(content)
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise LLMClientError("Failed LLM chat_vision_json call") from exc


def chat_vision_json(
    system_prompt: str,
    user_prompt: str,
    image_jpeg_bytes: bytes,
    *,
    timeout_s: float = 120.0,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    prompt_trace: PromptTraceMetadata | None = None,
) -> dict:
    """OpenAI-compatible vision call (single JPEG) using the same LLM_* settings as ``chat_json``."""
    langsmith_extra: dict[str, Any] | None = None
    if prompt_trace is not None:
        langsmith_extra = {"metadata": prompt_trace.to_langsmith_metadata()}
    return _chat_vision_json_impl(
        system_prompt,
        user_prompt,
        image_jpeg_bytes,
        temperature=temperature,
        timeout_s=timeout_s,
        max_tokens=max_tokens,
        langsmith_extra=langsmith_extra,
    )
