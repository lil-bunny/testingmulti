"""Tests for workflow error alert template rendering."""

from __future__ import annotations

from app.domain.error_catalog import BusinessError, workflow_error_payload
from app.domain.workflow_error_alert_templates import (
    build_workflow_error_alert_template_context,
    format_workflow_error_alert_template,
)


def test_build_template_context_uses_order_number_not_tender_id() -> None:
    context = build_workflow_error_alert_template_context(
        data={
            "tender_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "tender": {"order_number": "ORD-100", "customer_po": "PO-55"},
            "error": workflow_error_payload(
                code=BusinessError.MISSING_PACK_CODE.value,
                message=BusinessError.MISSING_PACK_CODE.description,
                category=BusinessError.CATEGORY,
            ),
        },
        error=workflow_error_payload(
            code=BusinessError.MISSING_PACK_CODE.value,
            message=BusinessError.MISSING_PACK_CODE.description,
            category=BusinessError.CATEGORY,
        ),
        workflow_lifecycle_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        workflow_run_id="cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    assert context["order_number"] == "ORD-100"
    assert context["customer_po"] == "PO-55"
    assert context["failure_reason"] == BusinessError.MISSING_PACK_CODE.description
    assert context["delivery_location_code_block"] == ""


def test_missing_placeholders_render_empty() -> None:
    context = build_workflow_error_alert_template_context(
        data={},
        error={"code": "missing_customer_po", "message": "Customer PO required", "category": "business"},
        workflow_lifecycle_id="wl",
        workflow_run_id="run",
    )
    subject = format_workflow_error_alert_template(
        "Exception PO {customer_po} order {order_number}",
        context,
    )
    assert subject == "Exception PO  order "
