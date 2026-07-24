#!/usr/bin/env python3
"""Manual tester for OpenAI-compatible chat / vision / PDF (matches llm_client).

Loads LLM_* from repo ``.env``. For ``--pdf`` / ``--vision``, uses the real POD
extraction prompts (Hub first, then ``prompts/fallbacks/``) — not a smoke summary.

Usage (from repo root):
    uv run python scripts/test_llm_client.py
    uv run python scripts/test_llm_client.py --vision path/to/image.jpg
    uv run python scripts/test_llm_client.py --pdf scripts/pod_logs/pod_119378438.pdf
    uv run python scripts/test_llm_client.py --pdf scripts/pod_logs/pod_119378438.pdf \\
        --prompt pod-pdf-extraction --broker-name "T3RA Logistics"
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / ".env")

from app.domain.vision_prompt_variables import pod_prompt_variables  # noqa: E402
from app.integrations.langsmith.fallback import (  # noqa: E402
    hub_id_from_tenant_prompt_ref,
    load_fallback_prompt,
)
from app.integrations.langsmith.render import render_system_user  # noqa: E402

# Prefer whole-document PDF Hub prompt; fall back to page-extraction schema.
_DEFAULT_PDF_PROMPT_REFS = ("pod-pdf-extraction", "pod-page-extraction")
_DEFAULT_VISION_PROMPT_REF = "pod-page-extraction"


def _extract_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    return json.loads(text)


def _env(name: str, default: str | None = None) -> str:
    value = (os.environ.get(name) or "").strip()
    if value:
        return value
    if default is not None:
        return default
    raise SystemExit(f"ERROR: {name} is missing (set it in .env)")


def _mime_for_image(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _load_prompt_template(tenant_prompt_ref: str):
    """Hub pull when LANGSMITH_API_KEY is set; else fallback JSON."""
    hub_id = hub_id_from_tenant_prompt_ref(tenant_prompt_ref)
    api_key = (os.environ.get("LANGSMITH_API_KEY") or "").strip()
    if api_key:
        try:
            from langsmith import Client

            pulled = Client(api_key=api_key).pull_prompt(tenant_prompt_ref)
            return pulled, "hub", tenant_prompt_ref
        except Exception as exc:
            print(f"WARN: Hub pull failed for {tenant_prompt_ref!r}: {exc}", file=sys.stderr)

    fallback = load_fallback_prompt(hub_id)
    return fallback, "fallback", hub_id


def _resolve_pod_prompts(
    *,
    prompt_refs: tuple[str, ...],
    broker_name: str | None,
) -> tuple[str, str, str, str]:
    """Return (system, user, source, ref_used)."""
    variables = pod_prompt_variables(broker_name)
    last_err: Exception | None = None
    for ref in prompt_refs:
        try:
            template, source, used = _load_prompt_template(ref)
            rendered = render_system_user(template, variables)
            system = (rendered.system or "").strip()
            user = (rendered.user or "").strip() or " "
            if not system:
                raise ValueError(f"empty system prompt for {ref!r}")
            return system, user, source, used
        except Exception as exc:
            last_err = exc
            print(f"WARN: could not load prompt {ref!r}: {exc}", file=sys.stderr)
    raise SystemExit(f"ERROR: no POD prompt available ({last_err})")


def _build_text_payload(model: str, system_prompt: str, user_prompt: str, temperature: float) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }


def _build_vision_payload(
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    temperature: float,
    max_tokens: int | None,
) -> dict:
    mime = _mime_for_image(image_path)
    b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    payload: dict = {
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
        "response_format": {"type": "json_object"},
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def _build_pdf_payload(
    model: str,
    system_prompt: str,
    user_prompt: str,
    pdf_path: Path,
    temperature: float,
    max_tokens: int | None,
) -> dict:
    """LiteLLM Admin UI shape: image_url + application/pdf data-URL."""
    b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
    data_url = f"data:application/pdf;base64,{b64}"

    payload: dict = {
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
        "response_format": {"type": "json_object"},
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual LLM tester using real POD prompts for vision/PDF",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--vision", metavar="IMAGE", help="Vision request + POD page prompt")
    mode.add_argument("--pdf", metavar="PDF", help="PDF request + POD PDF/page prompt")
    parser.add_argument(
        "--prompt",
        default=None,
        help=(
            "Hub/fallback prompt id. PDF default tries pod-pdf-extraction then "
            "pod-page-extraction. Vision default: pod-page-extraction."
        ),
    )
    parser.add_argument(
        "--broker-name",
        default=os.environ.get("BROKER_NAME", "T3RA Logistics"),
        help="Broker name for POD prompt variables (default: T3RA Logistics)",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(_env("LLM_REQUEST_TIMEOUT", "500")),
    )
    parser.add_argument("--max-tokens", type=int, default=None)
    args = parser.parse_args()

    base_url = _env("LLM_BASE_URL")
    api_key = _env("LLM_API_KEY")

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.is_file():
            print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
            return 1
        model = _env("LLM_PDF_MODEL", "pdf")
        refs = (args.prompt,) if args.prompt else _DEFAULT_PDF_PROMPT_REFS
        system_prompt, user_prompt, prompt_source, prompt_ref = _resolve_pod_prompts(
            prompt_refs=refs,
            broker_name=args.broker_name,
        )
        payload = _build_pdf_payload(
            model,
            system_prompt,
            user_prompt,
            pdf_path,
            args.temperature,
            args.max_tokens,
        )
        mode_name = "pdf"
        file_note = f"file={pdf_path} bytes={pdf_path.stat().st_size}"
    elif args.vision:
        image_path = Path(args.vision)
        if not image_path.is_file():
            print(f"ERROR: image not found: {image_path}", file=sys.stderr)
            return 1
        model = _env("LLM_VISION_MODEL", "vision")
        refs = (args.prompt or _DEFAULT_VISION_PROMPT_REF,)
        system_prompt, user_prompt, prompt_source, prompt_ref = _resolve_pod_prompts(
            prompt_refs=refs,
            broker_name=args.broker_name,
        )
        payload = _build_vision_payload(
            model,
            system_prompt,
            user_prompt,
            image_path,
            args.temperature,
            args.max_tokens,
        )
        mode_name = "vision"
        file_note = f"file={image_path} bytes={image_path.stat().st_size}"
    else:
        model = _env("LLM_CHAT_MODEL", "chat")
        system_prompt = (
            "You are a strict JSON generator. Respond ONLY with a JSON object, "
            "no prose, no code fences."
        )
        user_prompt = 'Return a JSON object: {"ok": true, "echo": "freightx-llm-test"}'
        payload = _build_text_payload(model, system_prompt, user_prompt, args.temperature)
        mode_name = "chat"
        file_note = None
        prompt_source = "inline"
        prompt_ref = "smoke-chat"

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print()
    print(f"POST {endpoint}")
    print(
        f"model={model} temperature={args.temperature} mode={mode_name} "
        f"timeout={args.timeout}"
    )
    print(f"prompt={prompt_ref} source={prompt_source} broker={args.broker_name!r}")
    if file_note:
        print(file_note)
    print("-" * 40)

    try:
        with httpx.Client(timeout=args.timeout) as client:
            response = client.post(endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        print(f"ERROR: request failed: {exc}", file=sys.stderr)
        return 1

    print(f"HTTP {response.status_code}")
    print("-" * 40)

    try:
        body = response.json()
        print(json.dumps(body, indent=2))
    except json.JSONDecodeError:
        print(response.text)
        return 1 if not response.is_success else 0

    if not response.is_success:
        return 1

    print("-" * 40)
    print("Extracted message.content:")
    try:
        content = body["choices"][0]["message"]["content"]
        print(content)
        print("-" * 40)
        print("Parsed JSON:")
        print(json.dumps(_extract_json(content), indent=2))
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        print(f"(could not parse assistant content: {exc})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
