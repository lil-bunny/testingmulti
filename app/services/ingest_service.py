"""
Central ingest orchestration.

Callers (HTTP webhooks, Celery, other services) stay thin; persistence and vendor
work happen here or in delegated repos/tools as behavior is added.
"""

from __future__ import annotations

import base64
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_BINARY_BYTES = 5 * 1024 * 1024


def _looks_like_xlsx(file_name: str | None, mime_type: str | None) -> bool:
    fn = (file_name or "").lower()
    if fn.endswith(".xlsx"):
        return True
    mt = (mime_type or "").lower()
    return "spreadsheetml" in mt


def _to_json_safe(value: Any, *, allow_nested_binary: bool = False) -> Any:
    """Recursive conversion to plain JSON-compatible Python values."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, memoryview):
        return _to_json_safe(value.tobytes(), allow_nested_binary=allow_nested_binary)

    try:
        import pandas as pd

        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                return None
            return value.isoformat()
    except ImportError:
        pass

    from datetime import date, datetime, time

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()

    if isinstance(value, (bytes, bytearray)):
        if not allow_nested_binary:
            raise ValueError(
                "bytes values nested in dict/list cannot be stored as JSON "
                "(pass allow_nested_binary=True to encode as base64)"
            )
        b = bytes(value)
        return {
            "encoding": "base64",
            "content": base64.b64encode(b).decode("ascii"),
        }

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _to_json_safe(v, allow_nested_binary=allow_nested_binary)
        return out

    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v, allow_nested_binary=allow_nested_binary) for v in value]

    if isinstance(value, set):
        try:
            ordered = sorted(value, key=lambda x: (str(type(x).__name__), str(x)))
        except TypeError:
            ordered = list(value)
        return [_to_json_safe(v, allow_nested_binary=allow_nested_binary) for v in ordered]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        return _to_json_safe(dumped, allow_nested_binary=allow_nested_binary)

    try:
        import numpy as np

        if isinstance(value, np.generic):
            return _to_json_safe(value.item(), allow_nested_binary=allow_nested_binary)
    except ImportError:
        pass

    return str(value)


def _finalize_jsonb_payload(payload: Any, *, allow_nested_binary: bool) -> Any:
    """Sanitize then force a JSON round-trip; ``default=str`` catches stray types."""

    sanitized = _to_json_safe(payload, allow_nested_binary=allow_nested_binary)
    return json.loads(json.dumps(sanitized, default=str))


def _normalize_storable_payload(
    data: Any | None,
    *,
    parse_spreadsheet: bool,
    file_name: str | None,
    mime_type: str | None,
    max_binary_bytes: int,
    spreadsheet_header: int | None = 0,
) -> dict[str, Any]:
    """
    Produce a plain ``dict`` storable as ``jsonb``.

    ``str`` payloads: valid JSON parses; non-object roots become ``{\"parsed\": ...}``;
    non-JSON text becomes ``{\"raw_text\": ...}``.
    ``bytes``: base64 envelope; optional spreadsheet tree when hinted and requested.
    """
    if data is None:
        return {}

    if isinstance(data, dict):
        return data

    if isinstance(data, str):
        text = data.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}
        if isinstance(parsed, dict):
            return parsed
        return {"parsed": parsed}

    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        if len(raw) > max_binary_bytes:
            raise ValueError(
                f"binary payload ({len(raw)} bytes) exceeds max_binary_bytes ({max_binary_bytes})"
            )
        envelope: dict[str, Any] = {
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }
        if parse_spreadsheet and _looks_like_xlsx(file_name, mime_type):
            from app.utils.excel import xlsx_bytes_to_sheet_records

            envelope["spreadsheet"] = xlsx_bytes_to_sheet_records(
                raw, header=spreadsheet_header
            )
        return envelope

    raise ValueError(
        f"data must be None, dict, str, or bytes, got {type(data).__name__}"
    )


def ingest_data(
    source_type: str,
    tenant_id: str,
    file_name: str | None = None,
    *,
    data: Any | None = None,
    data_type: str | None = None,
    mime_type: str | None = None,
    parse_spreadsheet: bool = False,
    spreadsheet_header: int | None = 0,
    max_binary_bytes: int | None = None,
    allow_nested_binary: bool = False,
) -> dict[str, Any]:
    """
    Entry point for ingesting data by source type and tenant.

    ``data`` may be:

    - ``None`` — empty object ``{}``
    - ``dict`` — webhook / job envelope (non-JSON-native nested values are sanitized)
    - ``str`` — JSON object becomes a dict; other JSON roots become ``{\"parsed\": ...}``;
      invalid JSON becomes ``{\"raw_text\": ...}``
    - ``bytes`` — stored as ``{\"encoding\": \"base64\", \"content\": ...}``; if
      ``parse_spreadsheet`` is true and ``file_name`` / ``mime_type`` indicate ``.xlsx``,
      a ``spreadsheet`` key with row records is added (see ``app.utils.excel``).

    ``data_type`` labels the logical import kind ( echoed on the return value for callers
    that persist rows, e.g. ``data_imports.data_type``).

    The returned ``data`` field is safe to persist as PostgreSQL ``jsonb`` (JSON round-trip).

    Raises:
        ValueError: Missing ``source_type`` / ``tenant_id``, oversized binary, unsupported
            ``data`` type, nested ``bytes`` without ``allow_nested_binary``, or ``data_type``
            provided but blank after strip.
    """

    st = (source_type or "").strip()
    tid = (tenant_id or "").strip()
    fn = (file_name or "").strip() or None
    mt = (mime_type or "").strip() or None
    cap = max_binary_bytes if max_binary_bytes is not None else DEFAULT_MAX_BINARY_BYTES
    dt: str | None = None
    if data_type is not None:
        dts = str(data_type).strip()
        if not dts:
            raise ValueError("data_type cannot be blank when provided")
        dt = dts

    if not st:
        raise ValueError("source_type is required")
    if not tid:
        raise ValueError("tenant_id is required")
    if cap < 1:
        raise ValueError("max_binary_bytes must be >= 1")

    payload = _normalize_storable_payload(
        data,
        parse_spreadsheet=parse_spreadsheet,
        file_name=fn,
        mime_type=mt,
        max_binary_bytes=cap,
        spreadsheet_header=spreadsheet_header,
    )
    storable = _finalize_jsonb_payload(
        payload, allow_nested_binary=allow_nested_binary
    )
    if not isinstance(storable, dict):
        storable = {"parsed": storable}

    logger.info(
        "ingest_data source_type=%s tenant_id=%s data_type=%s file_name=%s data_keys=%s",
        st,
        tid,
        dt,
        fn,
        sorted(storable.keys()),
    )

    return {
        "status": "stubbed",
        "source_type": st,
        "tenant_id": tid,
        "data_type": dt,
        "file_name": fn,
        "data": storable,
    }
