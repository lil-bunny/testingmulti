"""Workflow node: activity log transitions after TMS POD upload."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.models.activity_type import ActorType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_tms_upload_activity import (
    PodTmsUploadOutcome,
    record_pod_tms_upload_activity as record_pod_tms_upload_activity_fn,
    scope_from_lifecycle_row,
)
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


def _resolve_actor(state) -> tuple[ActorType, str | None]:
    event_type = str(state.data.get("event_type") or "").strip()
    if event_type != WorkflowRunEventType.MANUAL_POD_UPLOAD.value:
        return ActorType.SYSTEM, None
    user_id = str(state.data.get("uploaded_by_user_id") or "").strip()
    if user_id:
        return ActorType.USER, user_id
    return ActorType.SYSTEM, None


def _upload_outcome(turvo_result: dict[str, Any]) -> PodTmsUploadOutcome:
    if turvo_result.get("success"):
        return "uploaded"
    message = str(turvo_result.get("message") or "").lower()
    if "already" in message:
        return "skipped"
    return "failed"


def record_pod_tms_upload_activity(state):
    """Write TMS upload activity logs from ``turvo_upload_result`` in graph state."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = str(state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or state.data.get("execution_id") or "").strip()
    shipment_id = str(state.data.get("shipment_id") or "").strip()
    turvo_result = state.data.get("turvo_upload_result") or {}

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "record_pod_tms_upload_activity skipped missing ids lifecycle_id=%s run_id=%s",
            wl_id or None,
            run_id or None,
        )
        state.data["pod_tms_upload_activity_recorded"] = False
        return state

    row = WorkflowLifecycleService().read_lifecycle_row_by_id(wl_id)
    if not row:
        logger.warning(
            "record_pod_tms_upload_activity skipped lifecycle row not found id=%s",
            wl_id,
        )
        state.data["pod_tms_upload_activity_recorded"] = False
        return state

    scope = scope_from_lifecycle_row(
        tenant_id=tenant_id,
        workflow_lifecycle_id=wl_id,
        workflow_run_id=run_id,
        lifecycle_row=row,
        shipments_row_id=state.data.get("shipments_row_id"),
    )
    outcome = _upload_outcome(turvo_result if isinstance(turvo_result, dict) else {})
    extra: dict[str, Any] = {}
    doc = turvo_result.get("document") if isinstance(turvo_result, dict) else None
    if isinstance(doc, dict) and doc.get("id"):
        extra["tms_document_id"] = doc["id"]
    optimization = turvo_result.get("optimization") if isinstance(turvo_result, dict) else None
    if isinstance(optimization, dict) and optimization:
        extra["optimization"] = optimization
    if outcome == "failed":
        extra["error_code"] = "tms_upload_failed"
        fail_message = str(turvo_result.get("message") or "").strip()
        if fail_message:
            extra["error_message"] = fail_message[:500]
        if isinstance(turvo_result, dict) and turvo_result.get("status_code") is not None:
            extra["turvo_status_code"] = turvo_result.get("status_code")
    uploaded_by = str(state.data.get("uploaded_by") or "").strip()
    if uploaded_by:
        extra["uploaded_by"] = uploaded_by

    actor_type, actor_id = _resolve_actor(state)

    recorded = record_pod_tms_upload_activity_fn(
        scope=scope,
        shipment_id=shipment_id,
        outcome=outcome,
        extra_metadata=extra or None,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    state.data["pod_tms_upload_activity_recorded"] = recorded
    state.data["pod_tms_upload_outcome"] = outcome
    return state
