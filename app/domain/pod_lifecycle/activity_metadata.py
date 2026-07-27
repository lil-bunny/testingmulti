"""POD ``activity_logs.metadata`` builders — default ``None``, allowlist only.

Every POD activity row should use ``metadata=None`` unless the timeline needs a
pointer the row/description does not already carry. Confidence, summaries, and
validation outcomes live in ``document_analysis`` (``confidence_score`` column +
``results`` JSONB). Services call these builders; nodes never inline dicts.

Adding a new POD activity step: add a named builder here, call it from the
owning service, and extend ``tests/test_pod_activity_metadata.py``.
"""

from __future__ import annotations

import os
from typing import Any

from app.domain.pod_lifecycle.guards import is_email_pod_event

POD_ACTIVITY_METADATA_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "workflow_lifecycle_id",
        "thread_id",
        "shipment_id",
        "shipments_row_id",
        "load_id",
        "source",
        "extraction_confidence",
        "validation_confidence",
        "confidence_score",
        "validation_summary",
        "validation_skipped",
        "overall_status",
        "attachment_normalization",
        "pod_analysis_results",
        "document_analysis_pod",
        "reason",
        "workflow_shadow_mode",
        "shadow_mail_redirect",
        "shadow_mail_to",
        "error_code",
        "error_message",
        "turvo_status_code",
        "optimization",
    }
)


def compact(**kwargs: Any) -> dict[str, Any] | None:
    """Build dict from non-empty values; return ``None`` if empty."""
    meta: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict, tuple, set)) and not value:
            continue
        meta[key] = value
    return meta or None


def upload_action_metadata(
    data: dict[str, Any],
    *,
    documents_pod: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """S3 upload ACTION: ``object_key``, ``document_id``, optional email basenames."""
    merged_key = data.get("pod_merged_pdf_object_key")
    object_key = str(merged_key).strip() if merged_key is not None and str(merged_key).strip() else None

    document_id: str | None = None
    source_keys: list[str] = []
    if isinstance(documents_pod, dict):
        raw_id = documents_pod.get("id")
        if raw_id is not None and str(raw_id).strip():
            document_id = str(raw_id).strip()
        persist_meta = documents_pod.get("metadata")
        if isinstance(persist_meta, dict):
            raw_keys = persist_meta.get("source_object_keys")
            if isinstance(raw_keys, list):
                source_keys = [str(k).strip() for k in raw_keys if k and str(k).strip()]

    if not source_keys:
        for raw in data.get("pod_source_object_keys") or []:
            if raw and str(raw).strip():
                source_keys.append(str(raw).strip())

    source_object_keys: list[str] | None = None
    if source_keys and is_email_pod_event(data):
        basenames = [os.path.basename(k) for k in source_keys if k]
        source_object_keys = basenames or None

    return compact(
        object_key=object_key,
        document_id=document_id,
        source_object_keys=source_object_keys,
    )


def upload_failure_action_metadata(data: dict[str, Any]) -> dict[str, Any] | None:
    """Upload failure ACTION: ``error`` when normalization failed."""
    normalization = data.get("attachment_normalization")
    if isinstance(normalization, dict):
        reason = normalization.get("error") or normalization.get("reason")
        if reason is not None and str(reason).strip():
            return compact(error=str(reason).strip())
    return compact(error="pod_s3_upload_not_succeeded")


def processed_failure_action_metadata(data: dict[str, Any]) -> dict[str, Any] | None:
    """Processed failure ACTION: ``error`` from analysis results when present."""
    results = data.get("pod_analysis_results")
    if isinstance(results, dict):
        reason = results.get("reason") or results.get("error")
        if reason is not None and str(reason).strip():
            return compact(error=str(reason).strip())
    return compact(error="pod_analysis_not_stored")


def extraction_action_metadata(document_analysis_pod: dict[str, Any] | None) -> dict[str, Any] | None:
    """LLM extraction ACTION: ``document_analysis_id`` pointer only."""
    if not isinstance(document_analysis_pod, dict):
        return None
    analysis_id = document_analysis_pod.get("id")
    if analysis_id is None or not str(analysis_id).strip():
        return None
    return compact(document_analysis_id=str(analysis_id).strip())


def tms_action_metadata(
    *,
    outcome: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """TMS upload ACTION: ``tms_document_id``, ``uploaded_by``, ``outcome``."""
    extra = extra or {}
    tms_document_id = extra.get("tms_document_id")
    uploaded_by = extra.get("uploaded_by")
    return compact(
        tms_document_id=str(tms_document_id).strip() if tms_document_id else None,
        uploaded_by=str(uploaded_by).strip() if uploaded_by else None,
        outcome=outcome,
    )


def reminder_action_metadata(step: int) -> dict[str, Any] | None:
    """Reminder email ACTION: ``reminder_step`` only."""
    return compact(reminder_step=step)


def assert_allowlisted_keys(meta: dict[str, Any] | None, *, allowed: frozenset[str]) -> None:
    """Test helper: raise when metadata contains keys outside the allowlist."""
    if not meta:
        return
    extra = set(meta.keys()) - allowed
    if extra:
        raise AssertionError(f"unexpected metadata keys: {sorted(extra)}")


def assert_no_forbidden_keys(meta: dict[str, Any] | None) -> None:
    """Test helper: raise when metadata contains forbidden keys."""
    if not meta:
        return
    found = set(meta.keys()) & POD_ACTIVITY_METADATA_FORBIDDEN_KEYS
    if found:
        raise AssertionError(f"forbidden metadata keys: {sorted(found)}")
