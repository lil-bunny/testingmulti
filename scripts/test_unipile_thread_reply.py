"""
Exercise Unipile ``reply_to_thread`` (same code path as POD reminders / Celery).

From repo root:

  uv run python scripts/test_unipile_thread_reply.py payload.json
  uv run python scripts/test_unipile_thread_reply.py payload.json --twice
  uv run python scripts/test_unipile_thread_reply.py payload.json --count 3 --sleep 30
  uv run python scripts/test_unipile_thread_reply.py payload.json --twice --sleep 10
  uv run python scripts/test_unipile_thread_reply.py payload.json --preview-only

  # No JSON file — pass thread id on the command line (overrides payload thread_id if both given):
  uv run python scripts/test_unipile_thread_reply.py --preview-only --thread-id "AAQkA..."
  uv run python scripts/test_unipile_thread_reply.py --thread-id "AAQkA..." --twice
  uv run python scripts/test_unipile_thread_reply.py --thread-id "AAQkA..." --count 3 --sleep 30

Payload JSON (file or ``-`` for stdin):

  {
    "thread_id": "required — Unipile/Outlook thread id",
    "account_id": "optional — overrides UNIPILE_ACCOUNT_ID in .env",
    "body": "optional — defaults to POD_REMINDER_EMAIL_BODY",
    "subject": "optional — null keeps thread-derived subject",
    "reply_to_message_id": "optional — explicit parent for reply_to"
  }

Requires ``UNIPILE_API_KEY``, ``UNIPILE_DSN``, full app ``Settings`` (.env), and either
``UNIPILE_ACCOUNT_ID`` or ``account_id`` in the payload.

``--count N`` sends N in-thread replies (gap ``--sleep SEC``, default 10). ``--twice`` is shorthand for ``--count 2``.
If both ``--twice`` and ``--count`` are set, ``--count`` wins.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.unipile_service import Unipile, UnipileException  # noqa: E402
from app.tools.email import (  # noqa: E402
    _resolve_parent_id,
    _thread_email_summary,
    reply_to_thread,
)


def _load_payload(path: str | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = Path(path).read_text(encoding="utf-8") if path != "-" else sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("Payload must be a JSON object")
    return data


def _resolve_payload(path: str | None, thread_id_cli: str | None) -> dict[str, Any]:
    data = _load_payload(path)
    if thread_id_cli and str(thread_id_cli).strip():
        data = {**data, "thread_id": str(thread_id_cli).strip()}
    if not (data.get("thread_id") or "").strip():
        raise SystemExit(
            'Missing thread_id: set "thread_id" in JSON, use - for stdin, or pass --thread-id'
        )
    return data


def _resolve_account_id(payload: dict[str, Any]) -> str:
    acc = (payload.get("account_id") or "").strip() or (
        settings.UNIPILE_ACCOUNT_ID or ""
    ).strip()
    if not acc:
        raise SystemExit(
            "Missing account_id: set UNIPILE_ACCOUNT_ID in .env or pass account_id in payload."
        )
    return acc


def preview_only(payload: dict[str, Any]) -> None:
    thread_id = str(payload["thread_id"]).strip()
    account_id = _resolve_account_id(payload)
    reply_to_override = payload.get("reply_to_message_id")
    if reply_to_override is not None:
        reply_to_override = str(reply_to_override).strip() or None

    unipile = Unipile()
    exclude = unipile.get_account_email(account_id)
    res = unipile.list_emails(account_id=account_id, thread_id=thread_id, limit=50)
    items = res.get("items", []) if isinstance(res, dict) else []
    if not items:
        print("No messages in thread.")
        return
    sorted_emails = sorted(items, key=lambda e: e.get("date") or "", reverse=True)
    latest = sorted_emails[0]
    role_counts: dict[str, int] = {}
    for e in items:
        r = str(e.get("role") or "?")
        role_counts[r] = role_counts.get(r, 0) + 1
    print("thread_id:", thread_id)
    print("account_id:", account_id)
    print("mailbox (excluded from TO):", exclude)
    print("message_count:", len(items))
    print("role_counts:", role_counts)
    print("latest_by_date:", _thread_email_summary(latest))
    rid = _resolve_parent_id(unipile, latest, reply_to_override, account_id)
    print("resolved reply_to_id:", rid)


def run_send(payload: dict[str, Any]) -> bool:
    """Returns True if Unipile accepted the send, False if send_email reported failure."""
    thread_id = str(payload["thread_id"]).strip()
    account_id = _resolve_account_id(payload)
    body = (payload.get("body") or settings.POD_REMINDER_EMAIL_BODY or "").strip()
    subject = payload.get("subject")
    if subject is not None:
        subject = str(subject).strip() or None
    rt = payload.get("reply_to_message_id")
    if rt is not None:
        rt = str(rt).strip() or None

    result = reply_to_thread(
        thread_id=thread_id,
        body=body,
        account_id=account_id,
        subject=subject,
        reply_to_message_id=rt,
    )
    return bool(result.get("success", True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test Unipile reply_to_thread (Celery-equivalent path)."
    )
    parser.add_argument(
        "payload",
        nargs="?",
        default=None,
        help="Optional path to JSON payload, or - for stdin (omit if --thread-id is set)",
    )
    parser.add_argument(
        "--thread-id",
        dest="thread_id",
        default=None,
        metavar="ID",
        help="Unipile thread id (overrides thread_id in JSON when both are provided)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        metavar="N",
        help="Send N replies in a row (default: 1, or 2 if --twice without --count).",
    )
    parser.add_argument(
        "--twice",
        action="store_true",
        help="Shorthand for --count 2 (ignored if --count is set).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=10.0,
        metavar="SEC",
        help="Seconds between sends when N > 1 (default: 10)",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="List thread + print resolved reply_to_id without sending.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    payload = _resolve_payload(args.payload, args.thread_id)
    if args.preview_only:
        preview_only(payload)
        return 0

    n = args.count
    if n is None:
        n = 2 if args.twice else 1
    if n < 1:
        print("--count must be >= 1", file=sys.stderr)
        return 2

    try:
        for i in range(n):
            if i:
                print(f"\n--- send {i + 1}/{n} after {args.sleep}s ---\n", flush=True)
                time.sleep(args.sleep)
            if not run_send(payload):
                return 1
    except UnipileException as e:
        print("UnipileException:", e, file=sys.stderr)
        return 1
    except Exception as e:
        print(type(e).__name__ + ":", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
