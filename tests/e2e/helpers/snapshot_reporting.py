"""Terminal-friendly E2E DB snapshot banners (use with ``capsys.disabled()``)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    import pytest


def emit_db_snapshot_report(
    capsys: pytest.CaptureFixture[str],
    title: str,
    lines: list[str],
) -> None:
    """Print a framed block to the real terminal (bypasses pytest stdout capture)."""
    with capsys.disabled():
        print(flush=True)
        print("=" * 72, flush=True)
        print(f"  {title}", flush=True)
        print("=" * 72, flush=True)
        for line in lines:
            print(line, flush=True)
        print("=" * 72, flush=True)


def format_doc_lines(docs: list[dict[str, Any]], *, max_rows: int = 8) -> list[str]:
    out = [f"  documents: count={len(docs)}"]
    for i, d in enumerate(docs[:max_rows]):
        out.append(
            f"    [{i}] id={d.get('id')} type={d.get('type')} storage_key={d.get('storage_key')}"
        )
    if len(docs) > max_rows:
        out.append(f"    ... ({len(docs) - max_rows} more rows)")
    return out


def format_analysis_lines(rows: list[dict[str, Any]], *, max_rows: int = 8) -> list[str]:
    out = [f"  document_analysis: count={len(rows)}"]
    for i, r in enumerate(rows[:max_rows]):
        out.append(
            f"    [{i}] id={r.get('id')} type={r.get('analysis_type')}"
        )
    if len(rows) > max_rows:
        out.append(f"    ... ({len(rows) - max_rows} more rows)")
    return out
