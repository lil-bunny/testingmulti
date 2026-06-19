"""Celery payload for workflow error alert delivery."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.ingest_source_fields import (
    delivery_gap_context,
    pack_code_for_product_gap,
    source_delivery_address_code,
)
from app.domain.load_tendering_state import get_tender, get_tender_products


class WorkflowErrorAlertPayload(BaseModel):
    """Serializable context for one workflow error alert delivery attempt.

    ``exception_activity_log_id`` points at the failure ``exception`` activity row.
    """

    model_config = ConfigDict(extra="ignore")

    tenant_id: str
    workflow_name: str
    workflow_lifecycle_id: str
    workflow_run_id: str
    error: dict[str, Any]
    tenant_settings: dict[str, Any] = Field(default_factory=dict)
    tender_id: str | None = None
    pack_code: str | None = None
    delivery_address_code: str | None = None
    workflow_data: dict[str, Any] = Field(default_factory=dict)
    exception_activity_log_id: str | None = None

    @classmethod
    def from_workflow_state_data(
        cls,
        *,
        tenant_id: str,
        workflow_name: str,
        workflow_run_id: str,
        data: dict[str, Any],
        exception_activity_log_id: str | None = None,
    ) -> WorkflowErrorAlertPayload | None:
        """Build a Celery payload from graph state; returns ``None`` without a catalog error."""
        error = data.get("error")
        if not isinstance(error, dict) or not str(error.get("code") or "").strip():
            return None
        wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
        if not wl_id:
            return None
        wf_name = (workflow_name or str(data.get("workflow_name") or "")).strip()
        if not wf_name:
            return None
        tenant_settings = data.get("tenant_settings")
        if not isinstance(tenant_settings, dict):
            tenant_settings = {}
        tender = get_tender(data)
        pack_code = None
        delivery_address_code = None
        if tender:
            delivery_address_code = source_delivery_address_code(tender) or None
            for product in get_tender_products(tender):
                code = pack_code_for_product_gap(product)
                if code:
                    pack_code = code
                    break
        return cls(
            tenant_id=tenant_id,
            workflow_name=wf_name,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=workflow_run_id,
            error=error,
            tenant_settings=tenant_settings,
            tender_id=str(data.get("tender_id") or "").strip() or None,
            pack_code=pack_code or None,
            delivery_address_code=delivery_address_code or None,
            workflow_data=dict(data),
            exception_activity_log_id=str(exception_activity_log_id or "").strip() or None,
        )
