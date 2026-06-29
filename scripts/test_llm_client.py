#!/usr/bin/env python3
"""Manual tester for the OpenAI-compatible endpoint used by app/tools/llm_client.py.

Does NOT read .env or app settings. Prompts for base URL, API key, and model,
then POSTs to {BASE_URL}/chat/completions the same way chat_json / chat_vision_json do.

Usage:
    uv run python scripts/test_llm_client.py
    uv run python scripts/test_llm_client.py --vision /path/to/image.jpg

Optional env overrides (still no .env loading):
    LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=... uv run python scripts/test_llm_client.py
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import sys
from pathlib import Path

import httpx


def _extract_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            text = "\n".join(lines[1:-1]).strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
    return json.loads(text)


def _prompt(name: str, *, secret: bool = False, default: str | None = None) -> str:
    current = os.environ.get(name, "").strip()
    if current:
        return current

    label = name.replace("_", " ").title()
    if secret:
        value = getpass.getpass(f"{label}: ")
    elif default:
        value = input(f"{label} [{default}]: ").strip() or default
    else:
        value = input(f"{label}: ").strip()

    if not value:
        raise SystemExit(f"ERROR: {name} is required")
    return value


def _build_text_payload(model: str, system_prompt: str, user_prompt: str, temperature: float) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
    }


def _build_vision_payload(
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_path: Path,
    temperature: float,
    max_tokens: int | None,
) -> dict:
    image_bytes = image_path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_url = f"data:image/jpeg;base64,{b64}"

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
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Manual LLM client tester (no .env)")
    parser.add_argument(
        "--vision",
        metavar="IMAGE",
        help="Run chat_vision_json-style request with a JPEG image path",
    )
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("TEMPERATURE", "0.2")))
    parser.add_argument("--timeout", type=float, default=60.0, help="Request timeout in seconds")
    parser.add_argument("--max-tokens", type=int, default=None, help="Optional max_tokens (vision)")
    args = parser.parse_args()

    base_url = _prompt("LLM_BASE_URL")
    api_key = _prompt("LLM_API_KEY", secret=True)
    model = _prompt("LLM_MODEL", default="gpt-4o-mini")

    system_prompt = os.environ.get(
        "SYSTEM_PROMPT",
        "You are a strict JSON generator. Respond ONLY with a JSON object, no prose, no code fences.",
    )
    user_prompt = os.environ.get(
        "USER_PROMPT",
        'Return a JSON object: {"ok": true, "echo": "freightx-llm-test"}',
    )

    if args.vision:
        image_path = Path(args.vision)
        if not image_path.is_file():
            print(f"ERROR: image not found: {image_path}", file=sys.stderr)
            return 1
        user_prompt = os.environ.get(
            "USER_PROMPT",
            'Describe this image. Return a JSON object: {"description": "..."}',
        )
        payload = _build_vision_payload(
            model, system_prompt, user_prompt, image_path, args.temperature, args.max_tokens
        )
        mode = "vision"
    else:
        payload = _build_text_payload(model, system_prompt, user_prompt, args.temperature)
        mode = "text"

    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print()
    print(f"POST {endpoint}")
    print(f"model={model} temperature={args.temperature} mode={mode}")
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
        print("Parsed JSON (llm_client._extract_json):")
        print(json.dumps(_extract_json(content), indent=2))
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        print(f"(could not parse assistant content: {exc})", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
