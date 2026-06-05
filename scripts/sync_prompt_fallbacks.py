#!/usr/bin/env python3
"""Pull Hub prompt(s) and write LangChain-serialized fallbacks under ``prompts/fallbacks/``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.load.dump import dumps
from langchain_core.prompts import BasePromptTemplate
from langsmith import Client

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.core.config import settings  # noqa: E402
from app.integrations.langsmith.fallback import (  # noqa: E402
    fallback_path_for_hub_id,
    hub_id_from_tenant_prompt_ref,
)


def _langsmith_client() -> Client:
    api_key = (settings.LANGSMITH_API_KEY or "").strip()
    if not api_key:
        print(
            "LANGSMITH_API_KEY is not set. Add it to .env or export it, then retry.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return Client(api_key=api_key)


def sync_ref(ref: str, *, client: Client | None = None) -> Path:
    hub_id = hub_id_from_tenant_prompt_ref(ref)
    pulled = (client or _langsmith_client()).pull_prompt(ref)
    if not isinstance(pulled, BasePromptTemplate):
        raise TypeError(f"Hub ref {ref!r} did not return a prompt template")
    path = fallback_path_for_hub_id(hub_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(pulled), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        action="append",
        required=True,
        help="Hub ref including tag, e.g. carrier-ack-classify:production",
    )
    args = parser.parse_args()
    for ref in args.ref:
        path = sync_ref(ref.strip())
        print(json.dumps({"ref": ref, "path": str(path.relative_to(_REPO_ROOT))}))


if __name__ == "__main__":
    main()
