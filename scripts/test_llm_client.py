"""
Smoke-test ``app.tools.llm_client.chat_json`` against your configured LLM endpoint.

Requires a full ``agents-freightx/.env`` (Settings loads all required vars on import).
Override LLM settings via CLI flags or env vars before the call.

Run from ``agents-freightx/``:

  uv run python scripts/test_llm_client.py
  uv run python scripts/test_llm_client.py --base-url https://api.openai.com/v1 --model gpt-4o-mini --api-key sk-...

Non-LLM env vars get safe placeholders if missing so Settings can load.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow `uv run python scripts/test_llm_client.py` without manual PYTHONPATH.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Placeholders so Settings() can load when .env is LLM-only or incomplete.
_SETTINGS_DEFAULTS: dict[str, str] = {
    "DATABASE_HOST": "localhost",
    "DATABASE_PORT": "5432",
    "DATABASE_NAME": "freightx",
    "DATABASE_USER": "freightx",
    "DATABASE_PASSWORD": "freightx",
    "CELERY_BROKER_URL": "redis://localhost:6379/0",
    "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
    "UNIPILE_API_KEY": "test",
    "UNIPILE_DSN": "localhost",
    "OAUTH_REDIRECT_URI": "http://localhost:8001/oauth/callback",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "BUCKET_NAME": "test",
    "UNIPILE_WEBHOOK_SECRET": "test",
}


def _ensure_settings_env_defaults() -> None:
    for key, value in _SETTINGS_DEFAULTS.items():
        os.environ.setdefault(key, value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test LLM chat_json connectivity")
    parser.add_argument(
        "--base-url",
        help="Override LLM_BASE_URL (OpenAI-compatible /chat/completions base)",
    )
    parser.add_argument("--model", help="Override LLM_MODEL")
    parser.add_argument("--api-key", help="Override LLM_API_KEY")
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Request timeout in seconds (default: 60)",
    )
    return parser.parse_args()


def _mask_secret(value: str | None) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def main() -> int:
    load_dotenv(_ROOT / ".env.prod")
    _ensure_settings_env_defaults()
    args = _parse_args()

    if args.base_url:
        os.environ["LLM_BASE_URL"] = args.base_url
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.api_key:
        os.environ["LLM_API_KEY"] = args.api_key

    # Import after env overrides so Settings picks them up.
    from app.core.config import settings
    from app.tools.llm_client import LLMClientError, chat_json

    print("LLM config:")
    print(f"  LLM_BASE_URL = {settings.LLM_BASE_URL or '(not set)'}")
    print(f"  LLM_MODEL    = {settings.LLM_MODEL or '(not set)'}")
    print(f"  LLM_API_KEY  = {_mask_secret(settings.LLM_API_KEY)}")
    print()

    if not settings.LLM_BASE_URL or not settings.LLM_MODEL or not settings.LLM_API_KEY:
        print("ERROR: LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY must all be set.", file=sys.stderr)
        return 1

    system_prompt = (
        "You are a connectivity test assistant. "
        "Respond with JSON only, no markdown fences."
    )
    user_prompt = (
        'Reply with exactly this JSON shape: {"status": "ok", "message": "LLM is working"}'
    )

    print("Calling chat_json...")
    try:
        result = chat_json(
            system_prompt,
            user_prompt,
            temperature=0.0,
            timeout_s=args.timeout,
        )
        print(result)
    except LLMClientError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        if exc.__cause__ is not None:
            print(f"  cause: {exc.__cause__}", file=sys.stderr)
        return 1

    print("SUCCESS — parsed JSON response:")
    print(json.dumps(result, indent=2))

    if result.get("status") == "ok":
        print("\nLLM is working.")
        return 0

    print("\nLLM responded but payload did not match expected shape.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
