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
    """Shape LangSmith inputs as a single chat ``messages`` view (no duplicated prompt fields)."""
    system_prompt = inputs.get("system_prompt")
    user_prompt = inputs.get("user_prompt")
    traced: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
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


def _llm_trace_outputs(output: Any) -> dict[str, Any]:
    """Log a single content field for LangSmith; app still receives the parsed dict return value."""
    if isinstance(output, dict):
        return {"content": json.dumps(output, ensure_ascii=False)}
    return {"content": str(output)}


def _record_raw_llm_output(*, content: str) -> None:
    """Prefer raw model text on the span when available (overrides process_outputs dump of parsed)."""
    run_tree = get_current_run_tree()
    if run_tree is None:
        return
    run_tree.outputs = {"content": content}


def _merge_langsmith_extra(
    *,
    prompt_trace: PromptTraceMetadata | None,
    metadata: dict[str, Any] | None,
    tags: list[str] | None,
) -> dict[str, Any] | None:
    merged_meta: dict[str, Any] = {}
    if prompt_trace is not None:
        merged_meta.update(prompt_trace.to_langsmith_metadata())
    if metadata:
        for key, value in metadata.items():
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged_meta[key] = text
    extra: dict[str, Any] = {}
    if merged_meta:
        extra["metadata"] = merged_meta
    if tags:
        cleaned = [str(t).strip() for t in tags if str(t).strip()]
        if cleaned:
            extra["tags"] = cleaned
    return extra or None


@traceable(
    run_type="llm",
    name="chat_json",
    process_inputs=_llm_trace_inputs,
    process_outputs=_llm_trace_outputs,
)
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
        _record_raw_llm_output(content=content)
        return parsed
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise LLMClientError("Failed LLM chat_json call") from exc


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout_s: float | None = None,
    model: str | None = None,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """OpenAI-compatible chat completion; optional prompt/correlation metadata on LangSmith span."""
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    return _chat_json_impl(
        system_prompt,
        user_prompt,
        temperature=temperature,
        timeout_s=effective_timeout_s,
        model=model,
        langsmith_extra=_merge_langsmith_extra(
            prompt_trace=prompt_trace,
            metadata=metadata,
            tags=tags,
        ),
    )


@traceable(
    run_type="llm",
    name="chat_vision_json",
    process_inputs=_llm_trace_inputs,
    process_outputs=_llm_trace_outputs,
)
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
        _record_raw_llm_output(content=content)
        return parsed
    except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise LLMClientError("Failed LLM chat_vision_json call") from exc


def chat_vision_json(
    system_prompt: str,
    user_prompt: str,
    image_jpeg_bytes: bytes,
    *,
    timeout_s: float | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    model: str | None = None,
    image_mime_type: str = "image/jpeg",
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """OpenAI-compatible vision call (single image) using the same LLM_* settings as ``chat_json``."""
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    return _chat_vision_json_impl(
        system_prompt,
        user_prompt,
        image_jpeg_bytes,
        temperature=temperature,
        timeout_s=effective_timeout_s,
        max_tokens=max_tokens,
        model=model,
        image_mime_type=image_mime_type,
        langsmith_extra=_merge_langsmith_extra(
            prompt_trace=prompt_trace,
            metadata=metadata,
            tags=tags,
        ),
    )
