"""Opt-in E2E stubs for Unipile attachment fetch and S3 I/O (test / worker bootstrap only)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.config import settings

# ponytail: process-local dict; upgrade path is Redis if multi-worker E2E is needed
_MEM_S3: dict[str, bytes] = {}

_TRUTHY = frozenset({"1", "true", "yes"})


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def e2e_stub_attachments_enabled() -> bool:
    return _truthy_env("POD_E2E_STUB_ATTACHMENTS")


def e2e_stub_s3_enabled() -> bool:
    return _truthy_env("POD_E2E_STUB_S3")


def clear_e2e_s3_store() -> None:
    """Test helper: reset in-memory S3 between cases."""
    _MEM_S3.clear()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_fixture_path(raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = _repo_root() / path
    return path.resolve()


def _attachment_fixture_map() -> dict[str, str]:
    raw = os.environ.get("POD_E2E_ATTACHMENT_FIXTURES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"POD_E2E_ATTACHMENT_FIXTURES must be JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("POD_E2E_ATTACHMENT_FIXTURES must be a JSON object")
    return {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(k).strip()}


def _default_fixture_path() -> Path:
    explicit = os.environ.get("POD_E2E_ATTACHMENT_FIXTURE_PATH", "").strip()
    if explicit:
        return _resolve_fixture_path(explicit)
    return _repo_root() / "tests" / "fixtures" / "testpod.pdf"


def read_attachment_bytes(attachment_id: str) -> bytes:
    """Return fixture bytes for a synthetic Unipile ``attachment_id``."""
    att_id = str(attachment_id or "").strip()
    fixture_map = _attachment_fixture_map()
    if att_id and att_id in fixture_map:
        path = _resolve_fixture_path(fixture_map[att_id])
    else:
        path = _default_fixture_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"POD E2E fixture not found for attachment_id={att_id!r}: {path}"
        )
    return path.read_bytes()


def s3_upload_stub(
    *,
    file_content: bytes,
    filename: str,
    folder: str = settings.BUCKET_POD_ATTACHMENTS_FOLDER,
) -> dict[str, Any]:
    object_key = f"{folder}/{filename}"
    _MEM_S3[object_key] = file_content
    return {
        "success": True,
        "object_key": object_key,
        "error_message": None,
    }


def s3_download_stub(object_key: str) -> dict[str, Any]:
    key = (object_key or "").strip().lstrip("/")
    if not key:
        return {
            "success": False,
            "body": None,
            "object_key": None,
            "error_message": "empty_object_key",
        }
    body = _MEM_S3.get(key)
    if body is None:
        return {
            "success": False,
            "body": None,
            "object_key": key,
            "error_message": f"e2e_s3_missing_key: {key}",
        }
    return {
        "success": True,
        "body": body,
        "object_key": key,
        "error_message": None,
    }
