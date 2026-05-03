"""Domain enums for persisted document analysis rows."""

from __future__ import annotations

from enum import StrEnum


class DocumentAnalysisType(StrEnum):
    """Row ``analysis_type`` for the ``document_analysis`` table."""

    RATECON_EXTRACTION = "ratecon_extraction"
    POD_EXTRACTION = "pod_extraction"
    POD_VS_RATECON_COMPARISON = "pod_vs_ratecon_comparison"
