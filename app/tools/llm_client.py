"""OpenAI-compatible LLM client (Agentic / any chat-completions endpoint).

Async core (``achat_json``, ``achat_vision_json``, ``achat_pdf_json``) uses a shared
``AsyncOpenAI`` client per fan-out batch. Sync facades call ``asyncio.run`` for
one-shot sync callers (nodes, services, tools).
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    DefaultAsyncHttpxClient,
    RateLimitError,
)

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


LLMModality = Literal["chat", "vision", "pdf"]


def _modality_setting(modality: LLMModality) -> str | None:
    if modality == "pdf":
        return settings.LLM_PDF_MODEL
    if modality == "vision":
        return settings.LLM_VISION_MODEL
    return settings.LLM_CHAT_MODEL


def _resolve_model(model: str | None, *, modality: LLMModality) -> str:
    """Resolve model for one modality. Explicit ``model=`` wins; else the modality setting."""
    if model and model.strip():
        return model.strip()
    resolved = (_modality_setting(modality) or "").strip()
    if not resolved:
        raise LLMClientError(f"LLM config missing (model for {modality})")
    return resolved


def _require_llm_config() -> None:
    if not settings.LITELLM_PROXY_BASE_URL or not settings.LITELLM_API_KEY:
        raise LLMClientError("LLM config missing (base_url/api_key)")


def build_async_llm_client(
    *,
    timeout_s: float | None = None,
    max_connections: int = 1,
) -> AsyncOpenAI:
    """Create an ``AsyncOpenAI`` client bound to the current event loop.

    Caller owns lifecycle: use ``async with`` or ``await client.close()``.
    Pool ``max_connections`` should match the intended concurrency cap.
    """
    _require_llm_config()
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    pool_size = max(1, max_connections)
    return AsyncOpenAI(
        base_url=settings.LITELLM_PROXY_BASE_URL,
        api_key=settings.LITELLM_API_KEY,
        max_retries=0,
        timeout=effective_timeout_s,
        http_client=DefaultAsyncHttpxClient(
            limits=httpx.Limits(
                max_connections=pool_size,
                max_keepalive_connections=pool_size,
            ),
        ),
    )


@asynccontextmanager
async def _async_llm_client(
    client: AsyncOpenAI | None,
    *,
    timeout_s: float,
    max_connections: int = 1,
) -> AsyncIterator[AsyncOpenAI]:
    """Yield ``client`` if provided; otherwise build and close a one-shot client."""
    if client is not None:
        yield client
        return
    async with build_async_llm_client(
        timeout_s=timeout_s,
        max_connections=max_connections,
    ) as owned:
        yield owned


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
        "model": inputs.get("model") or _resolve_model(None, modality="chat"),
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
    pdf_bytes = inputs.get("pdf_bytes")
    if isinstance(pdf_bytes, (bytes, bytearray)):
        filename = inputs.get("pdf_filename") or "document.pdf"
        traced["pdf"] = {
            "filename": filename,
            "bytes": len(pdf_bytes),
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
                            "url": (
                                f"data:application/pdf;base64,"
                                f"<omitted {len(pdf_bytes)} bytes>"
                            ),
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


_OPENAI_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    APIStatusError,
    KeyError,
    json.JSONDecodeError,
    ValueError,
)


@traceable(
    run_type="llm",
    name="chat_json",
    process_inputs=_llm_trace_inputs,
    process_outputs=_llm_trace_outputs,
)
async def _achat_json_impl(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float,
    timeout_s: float,
    model: str | None = None,
    json_response_mode: bool = True,
    client: AsyncOpenAI,
) -> dict:
    """Call chat completions and parse JSON; raise ``LLMClientError`` on API/parse failure."""
    resolved_model = _resolve_model(model, modality="chat")
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "timeout": timeout_s,
    }
    if json_response_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        parsed = _extract_json(content)
        _record_raw_llm_output(content=content)
        return parsed
    except _OPENAI_ERRORS as exc:
        raise LLMClientError("Failed LLM chat_json call") from exc


@traceable(
    run_type="llm",
    name="chat_vision_json",
    process_inputs=_llm_trace_inputs,
    process_outputs=_llm_trace_outputs,
)
async def _achat_vision_json_impl(
    system_prompt: str,
    user_prompt: str,
    image_jpeg_bytes: bytes,
    *,
    temperature: float,
    timeout_s: float,
    max_tokens: int | None = None,
    model: str | None = None,
    image_mime_type: str = "image/jpeg",
    json_response_mode: bool = True,
    client: AsyncOpenAI,
) -> dict:
    """Call vision chat completions and parse JSON; raise ``LLMClientError`` on failure."""
    resolved_model = _resolve_model(model, modality="vision")
    mime = (image_mime_type or "image/jpeg").strip() or "image/jpeg"
    b64 = base64.b64encode(image_jpeg_bytes).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    kwargs: dict[str, Any] = {
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
        "timeout": timeout_s,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_response_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        parsed = _extract_json(content)
        _record_raw_llm_output(content=content)
        return parsed
    except _OPENAI_ERRORS as exc:
        raise LLMClientError("Failed LLM chat_vision_json call") from exc


@traceable(
    run_type="llm",
    name="chat_pdf_json",
    process_inputs=_llm_trace_inputs,
    process_outputs=_llm_trace_outputs,
)
async def _achat_pdf_json_impl(
    system_prompt: str,
    user_prompt: str,
    pdf_bytes: bytes,
    *,
    filename: str,
    temperature: float,
    timeout_s: float,
    max_tokens: int | None = None,
    model: str | None = None,
    json_response_mode: bool = True,
    client: AsyncOpenAI,
) -> dict:
    """Call PDF chat completions and parse JSON; raise ``LLMClientError`` on failure.

    LiteLLM Admin UI / Gemini-compatible gateways expect PDF as ``image_url`` with
    ``data:application/pdf;base64,...`` (not OpenAI ``type: file``).
    """
    resolved_model = _resolve_model(model, modality="pdf")
    # ``filename`` reserved for tracing/callers; gateway PDF path uses image_url only.
    _ = filename
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    data_url = f"data:application/pdf;base64,{b64}"

    kwargs: dict[str, Any] = {
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
        "timeout": timeout_s,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_response_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        parsed = _extract_json(content)
        _record_raw_llm_output(content=content)
        return parsed
    except _OPENAI_ERRORS as exc:
        raise LLMClientError("Failed LLM chat_pdf_json call") from exc


async def achat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout_s: float | None = None,
    model: str | None = None,
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    client: AsyncOpenAI | None = None,
) -> dict:
    """Async OpenAI-compatible chat completion; inject ``client`` for fan-out batches."""
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    async with _async_llm_client(client, timeout_s=effective_timeout_s) as resolved:
        return await _achat_json_impl(
            system_prompt,
            user_prompt,
            temperature=temperature,
            timeout_s=effective_timeout_s,
            model=model,
            json_response_mode=json_response_mode,
            client=resolved,
            langsmith_extra=_merge_langsmith_extra(
                prompt_trace=prompt_trace,
                metadata=metadata,
                tags=tags,
            ),
        )


async def achat_vision_json(
    system_prompt: str,
    user_prompt: str,
    image_jpeg_bytes: bytes,
    *,
    timeout_s: float | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    model: str | None = None,
    image_mime_type: str = "image/jpeg",
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    client: AsyncOpenAI | None = None,
) -> dict:
    """Async vision chat completion; inject ``client`` for fan-out batches."""
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    async with _async_llm_client(client, timeout_s=effective_timeout_s) as resolved:
        return await _achat_vision_json_impl(
            system_prompt,
            user_prompt,
            image_jpeg_bytes,
            temperature=temperature,
            timeout_s=effective_timeout_s,
            max_tokens=max_tokens,
            model=model,
            image_mime_type=image_mime_type,
            json_response_mode=json_response_mode,
            client=resolved,
            langsmith_extra=_merge_langsmith_extra(
                prompt_trace=prompt_trace,
                metadata=metadata,
                tags=tags,
            ),
        )


async def achat_pdf_json(
    system_prompt: str,
    user_prompt: str,
    pdf_bytes: bytes,
    *,
    filename: str = "document.pdf",
    timeout_s: float | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    model: str | None = None,
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    client: AsyncOpenAI | None = None,
) -> dict:
    """Async PDF chat completion; inject ``client`` for fan-out batches."""
    effective_timeout_s = (
        settings.LLM_REQUEST_TIMEOUT if timeout_s is None else timeout_s
    )
    async with _async_llm_client(client, timeout_s=effective_timeout_s) as resolved:
        return await _achat_pdf_json_impl(
            system_prompt,
            user_prompt,
            pdf_bytes,
            filename=filename,
            temperature=temperature,
            timeout_s=effective_timeout_s,
            max_tokens=max_tokens,
            model=model,
            json_response_mode=json_response_mode,
            client=resolved,
            langsmith_extra=_merge_langsmith_extra(
                prompt_trace=prompt_trace,
                metadata=metadata,
                tags=tags,
            ),
        )


def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.2,
    timeout_s: float | None = None,
    model: str | None = None,
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Sync facade over ``achat_json`` (one-shot ``asyncio.run`` per call)."""
    return asyncio.run(
        achat_json(
            system_prompt,
            user_prompt,
            temperature=temperature,
            timeout_s=timeout_s,
            model=model,
            json_response_mode=json_response_mode,
            prompt_trace=prompt_trace,
            metadata=metadata,
            tags=tags,
        )
    )


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
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Sync facade over ``achat_vision_json`` (one-shot ``asyncio.run`` per call)."""
    return asyncio.run(
        achat_vision_json(
            system_prompt,
            user_prompt,
            image_jpeg_bytes,
            timeout_s=timeout_s,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            image_mime_type=image_mime_type,
            json_response_mode=json_response_mode,
            prompt_trace=prompt_trace,
            metadata=metadata,
            tags=tags,
        )
    )


def chat_pdf_json(
    system_prompt: str,
    user_prompt: str,
    pdf_bytes: bytes,
    *,
    filename: str = "document.pdf",
    timeout_s: float | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    model: str | None = None,
    json_response_mode: bool = True,
    prompt_trace: PromptTraceMetadata | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Sync facade over ``achat_pdf_json`` (one-shot ``asyncio.run`` per call)."""
    return asyncio.run(
        achat_pdf_json(
            system_prompt,
            user_prompt,
            pdf_bytes,
            filename=filename,
            timeout_s=timeout_s,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            json_response_mode=json_response_mode,
            prompt_trace=prompt_trace,
            metadata=metadata,
            tags=tags,
        )
    )
