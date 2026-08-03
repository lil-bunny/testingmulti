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
    score: str
    review_summary: str
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
    stops = score.get("stops") if isinstance(score.get("stops"), list) else []
    if not stops:
        return "No Turvo purchase orders were found to score."

    parts: list[str] = []
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        stop_type = stop.get("stop_type")
        fields = stop.get("fields") if isinstance(stop.get("fields"), list) else []
        for field in fields:
            if not isinstance(field, dict):
                continue
            label = field.get("label")
            if label == "signature":
                parts.append(
                    f"signature {field.get('score')}/{field.get('max_score')}"
                )
            elif label == "reference_id":
                comparisons = field.get("comparisons") or []
                total = len(comparisons)
                matched = sum(1 for c in comparisons if isinstance(c, dict) and c.get("matched"))
                parts.append(
                    f"{stop_type} ref-id {field.get('score')}/{field.get('max_score')} "
                    f"({matched}/{total} POs)"
                )
        detail_fields = [f for f in fields if isinstance(f, dict) and f.get("category") == "shipment_detail"]
        if detail_fields:
            detail_scored = sum(int(f.get("score") or 0) for f in detail_fields)
            detail_max = sum(int(f.get("max_score") or 0) for f in detail_fields)
            parts.append(f"{stop_type} detail {detail_scored}/{detail_max}")

    summary = "; ".join(p for p in parts if p)
    if not summary:
        return "No Turvo purchase orders were found to score."

    exceptions = score.get("exceptions") if isinstance(score.get("exceptions"), list) else []
    exception_types = sorted(
        {e.get("exception_type") for e in exceptions if isinstance(e, dict) and e.get("exception_type")}
    )
    if exception_types:
        summary += f". Exceptions: {', '.join(exception_types)}."

    review_reasons = score.get("review_reasons") if isinstance(score.get("review_reasons"), list) else []
    if review_reasons:
        summary += " Review required: " + " ".join(str(reason) for reason in review_reasons)

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
        score_display = f"{round(float(final_score))}/100"
    except (TypeError, ValueError):
        return None

    pass_threshold = score.get("pass_threshold", 90)
    try:
        overall = "PASS" if float(final_score) >= pass_threshold else "FAIL"
    except (TypeError, ValueError):
        overall = "UNKNOWN"

    return PodAnalysisDisplayFields(
        load_id=load_id,
        score=score_display,
        review_summary=resolve_pod_scoring_summary(score),
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
        f"Load {fields.load_id} POD score {fields.score} "
        f"({fields.overall_status}). {fields.review_summary}"
    )


def pod_analysis_facts(fields: PodAnalysisDisplayFields) -> list[tuple[str, str]]:
    return [
        ("Load ID", fields.load_id or "—"),
        ("POD Score", fields.score or "—"),
        ("Status", fields.overall_status or "—"),
        ("Review summary", fields.review_summary or "—"),
    ]


def _template_context(fields: PodAnalysisDisplayFields) -> dict[str, str]:
    return {
        "load_id": fields.load_id,
        "score": fields.score,
        "review_summary": fields.review_summary,
        # Keep tenant-authored templates working during rollout.
        "confidence_score": fields.score,
        "validation_summary": fields.review_summary,
        "overall_status": fields.overall_status,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""
