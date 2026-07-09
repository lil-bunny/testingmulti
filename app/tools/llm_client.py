import base64
import json
from typing import Any

import httpx
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

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


def _resolve_model(model: str | None) -> str:
    resolved = (model or settings.LLM_MODEL or "").strip()
    if not resolved:
        raise LLMClientError("LLM config missing (model)")
    return resolved


def _llm_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Shape LangSmith inputs like a chat LLM run (prompts + metadata; no raw image bytes)."""
    system_prompt = inputs.get("system_prompt")
    user_prompt = inputs.get("user_prompt")
    traced: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "temperature": inputs.get("temperature"),
        "timeout_s": inputs.get("timeout_s"),
        "model": inputs.get("model") or settings.LLM_MODEL,
    }
    if "max_tokens" in inputs:
        traced["max_tokens"] = inputs["max_tokens"]
    image = inputs.get("image_jpeg_bytes")
    if isinstance(image, (bytes, bytearray)):
        mime = inputs.get("image_mime_type") or "image/jpeg"
        traced["image"] = {
            "mime_type": mime,
            "bytes": len(image),
            "present": True,
        }
        # Keep multimodal shape visible in the UI without uploading raw bytes.
        traced["messages"] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,<omitted {len(image)} bytes>",
                            "detail": "low",
                        },
                    },
                ],
            },
        ]
    return traced


def _record_raw_llm_output(*, content: str, model: str, parsed: dict) -> None:
    """Attach full completion text to the active LangSmith span (parsed JSON remains return value)."""
    run_tree = get_current_run_tree()
    if run_tree is None:
        return
    run_tree.outputs = {
        "content": content,
        "model": model,
        "parsed": parsed,
    }


@traceable(run_type="llm", name="chat_json", process_inputs=_llm_trace_inputs)
def _chat_json_impl(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float,
    timeout_s: float,
    model: str | None = None,
) -> dict:
    base_url = settings.LLM_BASE_URL
    resolved_model = _resolve_model(model)
    api_key = settings.LLM_API_KEY
    if not base_url or not api_key:
        raise LLMClientError("LLM config missing (base_url/api_key)")

    payload = {
        "model": resolved_model,
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
        parsed = _extract_json(content)
        _record_raw_llm_output(content=content, model=resolved_model, parsed=parsed)
        return parsed
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise LLMClientError("Failed LLM chat_json call") from exc


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout_s: float = 60.0,
    model: str | None = None,
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
        model=model,
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
    model: str | None = None,
    image_mime_type: str = "image/jpeg",
) -> dict:
    base_url = settings.LLM_BASE_URL
    resolved_model = _resolve_model(model)
    api_key = settings.LLM_API_KEY
    if not base_url or not api_key:
        raise LLMClientError("LLM config missing (base_url/api_key)")

    mime = (image_mime_type or "image/jpeg").strip() or "image/jpeg"
    b64 = base64.b64encode(image_jpeg_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    payload = {
        "model": resolved_model,
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
        parsed = _extract_json(content)
        _record_raw_llm_output(content=content, model=resolved_model, parsed=parsed)
        return parsed
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
    model: str | None = None,
    image_mime_type: str = "image/jpeg",
    prompt_trace: PromptTraceMetadata | None = None,
) -> dict:
    """OpenAI-compatible vision call (single image) using the same LLM_* settings as ``chat_json``."""
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
        model=model,
        image_mime_type=image_mime_type,
        langsmith_extra=langsmith_extra,
    )
