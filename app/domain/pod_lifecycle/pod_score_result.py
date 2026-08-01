"""PoD-vs-Turvo scoring result types (pure, no I/O).

Shared contract for ``score_pod``, the ``pod_scoring`` node, and Teams/activity
consumers.

Model:

- ``signature``: document-level delivery receiver proof, shared across POs
- ``stops``: one block per stop type (pickup / delivery) with the prorated
  reference-id result plus Pass 2 diff fields (dates + pickup/destination text)
- ``validation``: the 40-point validation bucket after the active strategy
  combines reference-id + Pass 2 (see ``validation_score``)
- ``final_score``: signature + validation bucket, always out of 100
- ``pass_threshold``: score floor for ``overall_status`` PASS (surfaced to the ops UI)
- ``po_scores``: per-Turvo-PO audit evidence (matched flag + page comparisons)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.domain.pod_lifecycle.validation_score import ValidationBucketScore

ExceptionType = Literal[
    "damage",
    "short_shipment",
    "over_shipment",
    "refused_delivery",
]
OverallStatus = Literal["PASS", "FAIL"]
StopType = Literal["pickup", "delivery"]
PASS_THRESHOLD = 90


@dataclass(frozen=True)
class PodFieldResult:
    """One compared field (signature, reference-id, or Pass 2 diff).

    ``target`` holds the Turvo side and ``source`` the POD side for the ops
    dashboard. Every field is always scored (0..max); which fields feed the
    overall score is decided by the validation-bucket strategy, not by the field
    itself.
    """

    label: str
    score: int
    max_score: int
    remark: str
    target: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class PodStopScore:
    """Reference-id and Pass 2 diff evidence for one Turvo stop type."""

    stop_type: StopType
    po_total: int
    po_matched: int
    reference_id: PodFieldResult
    diff: list[PodFieldResult] = field(default_factory=list)


@dataclass(frozen=True)
class PodPurchaseOrderScore:
    """Per-Turvo-PO audit evidence (matched status + page evidence)."""

    po_number: str
    stop_type: StopType
    matched: bool
    page_comparisons: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PodException:
    """Damage / short / over-shipment flag — never affects ``final_score``."""

    exception_type: ExceptionType
    detail: str


@dataclass(frozen=True)
class PodScoreResult:
    """Numeric PoD-vs-Turvo score and evidence for an Ops review decision."""

    signature: PodFieldResult
    stops: list[PodStopScore]
    validation: ValidationBucketScore
    final_score: int
    overall_status: OverallStatus
    max_score: int = 100
    pass_threshold: int = PASS_THRESHOLD
    po_scores: list[PodPurchaseOrderScore] = field(default_factory=list)
    exceptions: list[PodException] = field(default_factory=list)
    needs_action: bool = False
    remarks: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    stop_times: list[dict] = field(default_factory=list)
