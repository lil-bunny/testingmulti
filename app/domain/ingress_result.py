"""Typed outcomes for Unipile email L2 ingress (worker-only; not HTTP responses)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IngressOutcome = Literal["skipped", "enqueued", "processed", "no_match"]


@dataclass(frozen=True)
class IngressResult:
    """
    Worker-side outcome of one Unipile email L2 ingress pass.

    ``skipped`` — recognized event but guards blocked enqueue (out-of-order, duplicate comm).
    ``enqueued`` — workflow task(s) queued; see ``execution_ids``.
    ``processed`` — inline ingest completed in the ingress worker (no workflow enqueue).
    ``no_match`` — payload did not match any tenant ingress rule.
    """

    outcome: IngressOutcome
    reason: str | None = None
    event_type: str | None = None
    execution_ids: tuple[str, ...] = ()
