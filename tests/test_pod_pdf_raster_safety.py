"""Tests for OOM-safe POD PDF → JPEG conversion (Tracy-class MediaBox PDFs)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from app.domain.error_catalog import BusinessError
from app.domain.state import WorkflowState
from app.services.pod_lifecycle.extraction import (
    PodPdfTooLargeError,
    _effective_poppler_dpi,
    _try_extract_embedded_page_images,
    convert_pdf_to_images,
)
from app.tools import pod as pod_tools
from app.workflows.nodes import pod as pod_nodes

TRACY_PDF = Path(__file__).resolve().parents[1] / "scripts" / "llm" / "MCP-Tracy.pdf"
FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "testpod.pdf"


@pytest.mark.skipif(not TRACY_PDF.is_file(), reason="MCP-Tracy.pdf not present")
def test_tracy_pdf_uses_embedded_images_under_budget(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    paths = convert_pdf_to_images(
        str(TRACY_PDF),
        str(out_dir),
        dpi=200,
        max_side_px=2000,
        jpeg_quality=85,
        thread_count=1,
    )
    assert len(paths) == 8
    for path in paths:
        assert Path(path).is_file()
        with Image.open(path) as image:
            assert max(image.size) <= 2000
            # Must not be MediaBox@200DPI upscaled monsters (~6k–9k px).
            assert max(image.size) < 4000


@pytest.mark.skipif(not TRACY_PDF.is_file(), reason="MCP-Tracy.pdf not present")
def test_tracy_embedded_helper_returns_eight_pages(tmp_path: Path) -> None:
    out_dir = tmp_path / "emb"
    out_dir.mkdir()
    paths = _try_extract_embedded_page_images(
        str(TRACY_PDF),
        str(out_dir),
        max_side_px=2000,
        jpeg_quality=85,
        max_pages=None,
        max_page_bytes=80_000_000,
        max_total_bytes=400_000_000,
    )
    assert paths is not None
    assert len(paths) == 8


def test_effective_poppler_dpi_clamps_pathological_mediabox() -> None:
    assert _effective_poppler_dpi(requested_dpi=200, width_pt=2389, height_pt=3371) == 72
    assert _effective_poppler_dpi(requested_dpi=200, width_pt=612, height_pt=792) == 200


def test_conversion_memory_budget_raises_too_large(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with patch(
        "app.services.pod_lifecycle.extraction._try_extract_embedded_page_images",
        return_value=None,
    ), patch(
        "app.services.pod_lifecycle.extraction._convert_pdf_with_poppler_page_at_a_time",
        side_effect=PodPdfTooLargeError("over budget"),
    ):
        with pytest.raises(PodPdfTooLargeError):
            convert_pdf_to_images(str(pdf), str(tmp_path), dpi=200)


def test_pod_analysis_maps_pdf_too_large_error(tmp_path: Path) -> None:
    merged = tmp_path / "pod.pdf"
    merged.write_bytes(b"%PDF-1.4 x")

    with patch(
        "app.tools.pod.resolve_merged_pod_object_key",
        return_value=("pod_attachments/x.pdf", {"source": "state"}),
    ), patch(
        "app.tools.pod.extract_pod_from_pdf_path",
        side_effect=PodPdfTooLargeError("too big"),
    ):
        out = pod_tools.pod_analysis(
            {
                "shipment_id": "119407406",
                "pod_merged_pdf_object_key": "pod_attachments/x.pdf",
                "pod_merged_local_path": str(merged),
            }
        )
    assert out["success"] is False
    assert out["error"] == "pod_pdf_too_large"


def test_pod_analysis_node_raises_catalog_error_for_too_large_pdf() -> None:
    state = WorkflowState(
        tenant_id="t",
        tenant_slug="t3ra",
        execution_id="e1",
        data={"shipment_id": "119407406", "event_type": "email_received"},
    )
    with patch(
        "app.workflows.nodes.pod.get_pod_analysis",
        return_value={
            "success": False,
            "error": "pod_pdf_too_large",
            "shipment_id": "119407406",
        },
    ), patch("app.workflows.nodes.pod._cleanup_pod_attachment_stage"):
        result = pod_nodes.pod_analysis(state)

    data = result["data"] if isinstance(result, dict) else result.data
    assert data.get("error", {}).get("code") == BusinessError.POD_PDF_TOO_LARGE.value


@pytest.mark.skipif(not FIXTURE_PDF.is_file(), reason="tests/fixtures/testpod.pdf missing")
def test_letter_fixture_still_converts(tmp_path: Path) -> None:
    out_dir = tmp_path / "letter"
    out_dir.mkdir()
    try:
        paths = convert_pdf_to_images(
            str(FIXTURE_PDF),
            str(out_dir),
            dpi=150,
            max_side_px=2000,
            jpeg_quality=80,
            thread_count=1,
            max_pages=2,
        )
    except Exception as exc:
        if "poppler" in str(exc).lower() or "page count" in str(exc).lower():
            pytest.skip(f"poppler unavailable: {exc}")
        raise
    assert paths
    assert all(Path(p).is_file() for p in paths)
