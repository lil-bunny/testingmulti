"""E2E fixtures: load ``.env`` from repo root before importing ``app.*``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)


@pytest.fixture(scope="session")
def e2e_repo_root() -> Path:
    return _REPO_ROOT


@pytest.fixture
def pod_reply_fixture_payload(e2e_repo_root: Path) -> dict:
    path = e2e_repo_root / "tests" / "e2e" / "fixtures" / "pod_reply_webhook_payload.json"
    return json.loads(path.read_text(encoding="utf-8"))
