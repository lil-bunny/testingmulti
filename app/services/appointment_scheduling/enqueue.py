"""Enqueue appointment_scheduling workflow from Turvo ingress."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.ingress_constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)


def enqueue_appointment_scheduling_pickup_changed(
    *,
    tenant_slug: str,
    payload: dict[str, Any],
) -> str:
    execution_id = str(uuid.uuid4())
    body = {
        **payload,
        "event_type": WorkflowRunEventType.TURVO_PICKUP_CHANGED.value,
        "execution_id": execution_id,
        "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
    }
    task = run_workflow_async.apply_async(
        kwargs={
            "tenant_slug": tenant_slug,
            "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
            "payload": body,
        }
    )
    logger.info(
        "appointment_scheduling ingress queued workflow task_id=%s execution_id=%s shipment_id=%s",
        task.id,
        execution_id,
        payload.get("shipment_id"),
    )
    return execution_id


def enqueue_appointment_draft_send(
    *,
    tenant_slug: str,
    payload: dict[str, Any],
) -> str:
    execution_id = str(uuid.uuid4())
    body = {
        **payload,
        "event_type": WorkflowRunEventType.APPOINTMENT_DRAFT_SEND.value,
        "execution_id": execution_id,
        "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
    }
    task = run_workflow_async.apply_async(
        kwargs={
            "tenant_slug": tenant_slug,
            "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
            "payload": body,
        }
    )
    logger.info(
        "appointment_draft_send queued task_id=%s execution_id=%s lifecycle_id=%s",
        task.id,
        execution_id,
        payload.get("workflow_lifecycle_id"),
    )
    return execution_id
