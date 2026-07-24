"""Format Unipile webhook / FastAPI error responses for readable pytest output."""

from __future__ import annotations

import ast
import json
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    import httpx


def format_unipile_webhook_failure(resp: httpx.Response) -> str:
    """
    Pretty-print webhook error bodies.

    Handles:
    - FastAPI ``{"detail": "Attachment upload failed: [...]"}`` where the suffix is a Python
      repr of a list of dicts (from ``RuntimeError`` stringification in the app).
    - Nested JSON inside ``error_message`` (e.g. Unipile timeout payload).
    - Other JSON bodies via indented ``json.dumps``.
    """
    lines: list[str] = [f"=== Webhook HTTP {resp.status_code} ==="]
    text = (resp.text or "").strip()
    if not text:
        lines.append("(empty body)")
        return "\n".join(lines)

    try:
        body: Any = resp.json()
    except Exception:
        lines.append("--- raw body (not JSON) ---")
        lines.append(text[:8000])
        return "\n".join(lines)

    detail = body.get("detail")
    if isinstance(detail, str) and detail.startswith("Attachment upload failed:"):
        rest = detail[len("Attachment upload failed:") :].strip()
        lines.append("--- Attachment upload failures ---")
        try:
            items = ast.literal_eval(rest)
        except (SyntaxError, ValueError, MemoryError):
            lines.append(rest)
        else:
            if isinstance(items, list):
                for i, item in enumerate(items, 1):
                    lines.extend(_format_one_attachment_failure(i, item))
            else:
                lines.append(repr(items))
    elif isinstance(detail, list):
        lines.append(json.dumps({"detail": detail}, indent=2, default=str))
    elif isinstance(detail, dict):
        lines.append(json.dumps(body, indent=2, default=str))
    elif detail is not None:
        lines.append(json.dumps({"detail": detail}, indent=2, default=str))
    else:
        lines.append(json.dumps(body, indent=2, default=str))

    return "\n".join(lines)


def _format_one_attachment_failure(index: int, item: Any) -> list[str]:
    out: list[str] = []
    if not isinstance(item, dict):
        out.append(f"  [{index}] {item!r}")
        return out
    aid = item.get("attachment_id", "")
    out.append(f"  [{index}] attachment_id:")
    out.append(f"        {aid}")
    em = str(item.get("error_message") or "")
    out.append("        error_message:")
    for block in _prettify_error_message(em):
        for line in block.splitlines():
            out.append(f"        {line}")
    return out


def _prettify_error_message(msg: str) -> list[str]:
    msg = msg.strip()
    if not msg:
        return ["(none)"]

    marker = "Error retrieving attachment:"
    if marker in msg:
        _, _, after = msg.partition(marker)
        after = after.strip()
        blocks = [marker]
        if after.startswith("{") or after.startswith("["):
            try:
                parsed = json.loads(after)
                blocks.append(json.dumps(parsed, indent=2))
                return blocks
            except json.JSONDecodeError:
                pass
        blocks.append(after)
        return blocks

    if len(msg) > 200:
        return [msg[i : i + 100] for i in range(0, len(msg), 100)]
    return [msg]
