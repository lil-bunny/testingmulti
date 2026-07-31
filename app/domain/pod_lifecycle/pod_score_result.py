"""PoD-vs-Turvo scoring result types (pure, no I/O).

Shared contract for ``score_pod``, the ``pod_scoring`` node, and Teams/activity
consumers.
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
PASS_THRESHOLD = 90


@dataclass(frozen=True)
class PodFieldResult:
    """One scored field within Pass 1 or Pass 2 for a single PO."""

    label: str
    score: int
    max_score: int
    remark: str


@dataclass(frozen=True)
class PodPurchaseOrderScore:
    """Pass 1 (+ Pass 2 when ref-id fails) outcome for one Turvo PO."""

    po_number: str
    stop_type: Literal["pickup", "delivery"]
    pass1: list[PodFieldResult]
    pass2: list[PodFieldResult] | None
    po_total: int | None
    page_comparisons: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PodException:
    """Damage / short / over-shipment flag — never affects ``final_score``."""

    exception_type: ExceptionType
    detail: str


@dataclass(frozen=True)
class PodScoreResult:
    """Numeric PoD-vs-Turvo score and evidence for an Ops review decision."""

    po_scores: list[PodPurchaseOrderScore]
    final_score: int
    overall_status: OverallStatus
    exceptions: list[PodException] = field(default_factory=list)
    needs_action: bool = False
    pickup_signature_present: bool = True
    remarks: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    stop_times: list[dict] = field(default_factory=list)
