"""POD analysis Teams notification settings and message context (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PodLifecycleTeamsNotificationSettings(BaseModel):
    """``tenant_settings.pod_lifecycle.teams_notification``."""

    model_config = ConfigDict(extra="ignore")

    teams_webhook_url: str = Field(min_length=1)
    message_title: str = "POD analyzed — Load {load_id}"
    message_body: str | None = None


@dataclass(frozen=True)
class PodAnalysisDisplayFields:
    load_id: str
    confidence_score: str
    validation_summary: str
    overall_status: str


def parse_pod_teams_notification_settings(
    tenant_settings: dict[str, Any] | None,
) -> PodLifecycleTeamsNotificationSettings | None:
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("pod_lifecycle")
    if not isinstance(block, dict):
        return None
    raw = block.get("teams_notification")
    if not isinstance(raw, dict):
        return None
    try:
        return PodLifecycleTeamsNotificationSettings.model_validate(raw)
    except Exception:
        return None


def resolve_pod_analysis_load_id(data: dict[str, Any]) -> str:
    """Broker load label for Teams templates (email path often has shipment_id only)."""
    load_id = str(data.get("load_id") or "").strip()
    if load_id:
        return load_id

    shipment = data.get("shipment")
    if isinstance(shipment, dict):
        details = shipment.get("details")
        if isinstance(details, dict):
            custom_id = str(details.get("customId") or "").strip()
            if custom_id:
                return custom_id

    return str(data.get("shipment_id") or "").strip()


def resolve_pod_scoring_summary(score: dict[str, Any]) -> str:
    """Human-readable summary of a ``pod_scoring`` result dict for Teams/activity display."""
    po_scores = score.get("po_scores") if isinstance(score.get("po_scores"), list) else []
    if not po_scores:
        return "No Turvo purchase orders were found to score."

    parts = [
        f"{po.get('po_number')}: {po.get('po_total')}/100"
        for po in po_scores
        if isinstance(po, dict)
    ]
    summary = "; ".join(parts)

    exceptions = score.get("exceptions") if isinstance(score.get("exceptions"), list) else []
    exception_types = sorted(
        {e.get("exception_type") for e in exceptions if isinstance(e, dict) and e.get("exception_type")}
    )
    if exception_types:
        summary += f". Exceptions: {', '.join(exception_types)}."

    remarks = score.get("remarks") if isinstance(score.get("remarks"), list) else []
    if remarks:
        summary += " " + " ".join(str(r) for r in remarks)

    return summary.strip()


def pod_analysis_display_fields_from_data(
    data: dict[str, Any],
) -> PodAnalysisDisplayFields | None:
    """
    Map ``pod_scoring_results`` into Teams/activity display fields.

    Returns ``None`` when scoring was skipped, missing, or load id / score
    cannot be resolved.
    """
    scoring_results = data.get("pod_scoring_results")
    if not isinstance(scoring_results, dict) or not scoring_results.get("success"):
        return None
    if scoring_results.get("skipped"):
        return None

    score = scoring_results.get("score")
    if not isinstance(score, dict):
        return None

    load_id = resolve_pod_analysis_load_id(data)
    if not load_id:
        return None

    final_score = score.get("final_score")
    if final_score is None:
        return None
    try:
        confidence_score = f"{round(float(final_score))}/100"
    except (TypeError, ValueError):
        return None

    overall = str(score.get("result") or "UNKNOWN").strip().upper()
    if overall not in ("PASS", "FAIL", "UNKNOWN"):
        overall = "UNKNOWN"

    return PodAnalysisDisplayFields(
        load_id=load_id,
        confidence_score=confidence_score,
        validation_summary=resolve_pod_scoring_summary(score),
        overall_status=overall,
    )


def format_pod_analysis_title(
    template: str,
    *,
    fields: PodAnalysisDisplayFields,
) -> str:
    ctx = _template_context(fields)
    try:
        return template.format(**ctx)
    except KeyError:
        return template.format_map(_SafeFormatMap(ctx))


def format_pod_analysis_body(
    template: str | None,
    *,
    fields: PodAnalysisDisplayFields,
) -> str:
    if template and str(template).strip():
        ctx = _template_context(fields)
        try:
            return str(template).strip().format(**ctx)
        except KeyError:
            return str(template).strip().format_map(_SafeFormatMap(ctx))
    return (
        f"Load {fields.load_id} POD score {fields.confidence_score} "
        f"({fields.overall_status}). {fields.validation_summary}"
    )


def pod_analysis_facts(fields: PodAnalysisDisplayFields) -> list[tuple[str, str]]:
    return [
        ("Load ID", fields.load_id or "—"),
        ("POD Score", fields.confidence_score or "—"),
        ("Status", fields.overall_status or "—"),
        ("Summary", fields.validation_summary or "—"),
    ]


def _template_context(fields: PodAnalysisDisplayFields) -> dict[str, str]:
    return {
        "load_id": fields.load_id,
        "confidence_score": fields.confidence_score,
        "validation_summary": fields.validation_summary,
        "overall_status": fields.overall_status,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""
