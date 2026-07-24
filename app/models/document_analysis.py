"""Domain enums for persisted document analysis rows."""

from __future__ import annotations

from enum import StrEnum

# document_analysis.metadata key: ratecon PDF page count (POD strip OCR bound).
DOCUMENT_ANALYSIS_PAGE_COUNT_KEY = "page_count"


class DocumentAnalysisType(StrEnum):
    """Row ``analysis_type`` for the ``document_analysis`` table."""

    RATECON_EXTRACTION = "ratecon_extraction"
    POD_EXTRACTION = "pod_extraction"
    POD_VS_RATECON_COMPARISON = "pod_vs_ratecon_comparison"
