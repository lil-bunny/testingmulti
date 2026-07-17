"""Tests for parallel POD page vision fan-out."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.integrations.langsmith import RenderedPrompt
from app.integrations.langsmith.types import PromptLoadMetadata
from app.services.pod_lifecycle import extraction as pod_extraction


@pytest.mark.asyncio
async def test_analyze_pages_async_respects_concurrency_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(pod_extraction.settings, "POD_PAGE_CONCURRENCY", 2)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake_analyze_page_async(*args, **kwargs):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        async with lock:
            in_flight -= 1
        page_number = args[1]
        return {
            "page_number": page_number,
            "extracted_data": {"page_type": "BOL"},
            "load_id": "load",
        }

    image_paths = []
    for i in range(4):
        p = tmp_path / f"page_{i + 1}.jpg"
        p.write_bytes(b"\xff\xd8\xff" + b"x")
        image_paths.append(str(p))

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    with patch.object(
        pod_extraction,
        "analyze_page_async",
        side_effect=fake_analyze_page_async,
    ), patch.object(
        pod_extraction,
        "build_async_llm_client",
        return_value=FakeClient(),
    ):
        rows = await pod_extraction._analyze_pages_async(
            image_paths,
            vision_prompts=RenderedPrompt(system="sys", user="user"),
            prompt_trace=None,
            max_tokens=None,
            load_id="load",
        )

    assert len(rows) == 4
    assert sorted(r["page_number"] for r in rows) == [1, 2, 3, 4]
    assert max_in_flight <= 2


def test_extract_from_pdf_path_uses_parallel_analyze(monkeypatch, tmp_path):
    pdf_path = tmp_path / "pod.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    image_paths = []
    for i in range(3):
        p = tmp_path / f"page_{i + 1}.jpg"
        p.write_bytes(b"\xff\xd8\xff")
        image_paths.append(str(p))

    async def fake_analyze_pages_async(image_paths_arg, *, load_id, **kwargs):
        assert load_id == "pod"
        assert len(image_paths_arg) == 3
        return [
            {
                "page_number": n,
                "extracted_data": {"page_type": "BOL"},
                "load_id": load_id,
                "timestamp": "t",
            }
            for n in (1, 2, 3)
        ]

    monkeypatch.setattr(
        pod_extraction,
        "resolve_pod_vision_prompts",
        lambda tenant_settings, broker_name: (
            RenderedPrompt(system="sys", user="user"),
            PromptLoadMetadata(
                source="fallback",
                tenant_prompt_ref="pod-page-extraction:staging",
            ),
        ),
    )
    monkeypatch.setattr(pod_extraction, "convert_pdf_to_images", lambda *a, **k: image_paths)
    monkeypatch.setattr(pod_extraction, "_analyze_pages_async", fake_analyze_pages_async)

    page_results, final_pod_data, validation_issues, reconciliation_log = (
        pod_extraction.extract_from_pdf_path(str(pdf_path))
    )

    assert len(page_results) == 3
    assert [r["page_number"] for r in page_results] == [1, 2, 3]
    assert isinstance(final_pod_data, dict)
    assert isinstance(reconciliation_log, dict)
    assert isinstance(validation_issues, list)
