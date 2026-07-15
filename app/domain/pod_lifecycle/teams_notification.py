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

    for key in ("ratecon_analysis_results", "pod_vs_ratecon_analysis_results"):
        block = data.get(key)
        if not isinstance(block, dict):
            continue
        findings = block.get("findings") or {}
        if not isinstance(findings, dict):
            continue
        extracted = findings.get("extracted_fields") or {}
        if isinstance(extracted, dict):
            primary = str(extracted.get("primary_identifier") or "").strip()
            if primary:
                return primary

    return str(data.get("shipment_id") or "").strip()


def pod_analysis_display_fields_from_data(
    data: dict[str, Any],
) -> PodAnalysisDisplayFields | None:
    vs_results = data.get("pod_vs_ratecon_analysis_results")
    if not isinstance(vs_results, dict):
        return None

    load_id = resolve_pod_analysis_load_id(data)
    if not load_id:
        return None

    confidence_raw = vs_results.get("confidence_score")
    if confidence_raw is None:
        return None
    try:
        confidence_score = f"{float(confidence_raw):.2f}"
    except (TypeError, ValueError):
        return None

    validation_summary = str(vs_results.get("validation_summary") or "").strip()
    if not validation_summary:
        return None

    overall = str(vs_results.get("overall_status") or "UNKNOWN").strip().upper()
    if overall not in ("PASS", "FAIL", "UNKNOWN"):
        overall = "UNKNOWN"

    return PodAnalysisDisplayFields(
        load_id=load_id,
        confidence_score=confidence_score,
        validation_summary=validation_summary,
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
