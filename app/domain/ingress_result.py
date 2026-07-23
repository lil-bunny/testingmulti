"""Typed outcomes for Unipile email L2 ingress (worker-only; not HTTP responses)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IngressOutcome = Literal["skipped", "enqueued", "buffered", "processed", "no_match"]


@dataclass(frozen=True)
class IngressResult:
    """
    Outcome of one Unipile email ingress pass.

    ``skipped`` — recognized event but guards blocked enqueue.
    ``enqueued`` — graph Celery started (run-queue length became 1).
    ``buffered`` — Work item queued; start-next will publish later.
    ``processed`` — inline ingest completed (no graph enqueue).
    ``no_match`` — payload did not match any tenant ingress rule.
    """

    outcome: IngressOutcome
    reason: str | None = None
    event_type: str | None = None
    execution_ids: tuple[str, ...] = ()
