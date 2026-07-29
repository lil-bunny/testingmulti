"""Grep-guard: RateCon LLM analysis symbols must not reappear under ``app/``."""

from __future__ import annotations

from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"

_FORBIDDEN = (
    "vs_ratecon_validation",
    "RateconDocumentService().analyze_and_persist",
    "def analyze_and_persist",
    "_broker_name_from_ratecon_results",
    "pod_vs_ratecon_analysis",
)


def test_no_removed_ratecon_analysis_references_remain():
    hits: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in _FORBIDDEN:
            if needle in text:
                hits.append(f"{path}: {needle!r}")
    assert not hits, "Removed ratecon-analysis code re-appeared:\n" + "\n".join(hits)


def test_ratecon_analysis_node_not_registered():
    from app.workflows.registry import NODE_REGISTRY

    assert "ratecon_analysis" not in NODE_REGISTRY
