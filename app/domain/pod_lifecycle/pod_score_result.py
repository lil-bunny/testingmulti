"""PoD-vs-Turvo scoring result types (pure, no I/O).

Stored schema contract: flat field-wise scoring grouped by stop.

- Each stop has ``fields[]`` where every field carries ``label``, ``category``,
  ``score``, ``maxScore``. Optional keys: ``remark``, ``source``, ``target``,
  ``comparisons`` (for reference_id).
- Signature lives inside the delivery stop as an identity field.
- Root carries ``finalScore``, ``maxScore``, ``passThreshold``.
- ``exceptions``, ``remarks``, ``reviewReasons``, ``stopTimes`` are omitted
  when empty (not stored).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ExceptionType = Literal[
    "damage",
    "short_shipment",
    "over_shipment",
    "refused_delivery",
]
OverallStatus = Literal["PASS", "FAIL"]
StopType = Literal["pickup", "delivery"]
FieldCategory = Literal["identity", "shipment_detail"]

PASS_THRESHOLD = 90


@dataclass(frozen=True)
class PoComparison:
    """One PO comparison within a reference_id field."""

    po_number: str
    matched: bool
    source: str | None = None
    target: str | None = None


@dataclass(frozen=True)
class ScoredField:
    """One scored field within a stop.

    Base contract: label, category, score, max_score always present.
    Optional: remark, source, target, comparisons.
    """

    label: str
    category: FieldCategory
    score: int
    max_score: int
    remark: str | None = None
    source: str | None = None
    target: str | None = None
    comparisons: list[PoComparison] | None = None


@dataclass(frozen=True)
class StopScore:
    """All scored fields for one stop."""

    stop_type: StopType
    stop_order: int
    fields: list[ScoredField]
    stop_times: list[dict] | None = None


@dataclass(frozen=True)
class PodException:
    """Damage / short / over-shipment flag — never affects score."""

    exception_type: ExceptionType
    detail: str


@dataclass(frozen=True)
class PodScoreResult:
    """Root scoring result stored in document_analysis.results."""

    final_score: int
    max_score: int
    pass_threshold: int
    stops: list[StopScore]
    exceptions: list[PodException] | None = None
    remarks: list[str] | None = None
    review_reasons: list[str] | None = None
    needs_action: bool = True
