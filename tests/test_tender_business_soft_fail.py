"""Gelita outbound-tender soft-fail: warnings, vendor email footer, activity logs."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, format_error_message
from app.domain.state import WorkflowState
from app.domain.tender_business_warnings import (
    filter_primary_business_warnings,
    format_reason_for_failure_html,
    get_tender_business_warnings,
)
from app.workflows.nodes.gelita.record_tender_business_warnings import (
    record_tender_business_warnings,
)
from app.workflows.nodes.send_tender_email import send_tender_email
from app.workflows.utils.gelita_soft_fail import (
    gelita_tender_created_soft_fail_enabled,
    record_business_gap,
)
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def test_soft_fail_enabled_for_tender_created_and_routing_guide_failover() -> None:
    assert gelita_tender_created_soft_fail_enabled({"event_type": "tender_created"})
    assert gelita_tender_created_soft_fail_enabled(
        {"event_type": "escalation_due", "routing_guide_failover": True}
    )
    assert not gelita_tender_created_soft_fail_enabled(
        {"event_type": "escalation_due"}
    )
    assert not gelita_tender_created_soft_fail_enabled(
        {"event_type": "ack_received"}
    )


def _tender_created_state(*, tender: dict | None = None) -> WorkflowState:
    base_tender = {
        "load_type": "ltl",
        "delivery_date": "2026-06-20",
        "pickup_address": "GELITA USA\n123 Main St\nSIOUX CITY IA 51101",
        "delivery_address": "ACME\n456 Oak Ave\nCHICAGO IL 60601",
        "tender_products": [{"product_name": "Widget", "pack_code": "5366"}],
    }
    if tender:
        base_tender.update(tender)
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "event_type": "tender_created",
            "workflow_lifecycle_id": "lifecycle-1",
            "tender_id": "tender-1",
            "tenant_settings": load_tenant_settings_dev("gelita"),
            "tender": base_tender,
        },
    )


def test_format_reason_for_failure_html_empty_when_no_warnings() -> None:
    assert format_reason_for_failure_html([]) == ""


def test_format_reason_for_failure_html_red_italic_header_with_suffix() -> None:
    msg = format_error_message(BusinessError.MISSING_DELIVERY_DATE)
    html = format_reason_for_failure_html([{"code": "x", "message": msg}])
    assert "color: red" in html
    assert "font-style: italic" in html
    assert msg in html
    assert "Please update the field highlighted in red manually." in html


def test_format_reason_for_failure_html_omits_routing_guide_codes() -> None:
    lane_msg = format_error_message(BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND)
    dims_msg = format_error_message(BusinessError.MISSING_UNIT_DIMS, pack_code="5172")
    warnings = [
        {
            "code": BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND.value,
            "message": lane_msg,
        },
        {
            "code": BusinessError.MISSING_UNIT_DIMS.value,
            "message": dims_msg,
            "context": {"pack_code": "5172"},
        },
    ]

    html = format_reason_for_failure_html(warnings)

    assert lane_msg not in html
    assert dims_msg in html
    assert "Please update the field highlighted in red manually." in html


def test_format_reason_for_failure_html_empty_for_routing_guide_only() -> None:
    lane_msg = format_error_message(BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND)
    html = format_reason_for_failure_html(
        [
            {
                "code": BusinessError.ROUTING_GUIDE_LANE_NOT_FOUND.value,
                "message": lane_msg,
            }
        ]
    )
    assert html == ""


def test_filter_primary_business_warnings_collapses_duplicate_catalog_profile_gaps() -> None:
    dims_msg = format_error_message(BusinessError.MISSING_UNIT_DIMS, pack_code="3002")
    generic_msg = "Unit dimensions are missing."
    warnings = [
        {
            "code": BusinessError.MISSING_UNIT_DIMS.value,
            "message": dims_msg,
            "context": {"pack_code": "3002", "tender_product_id": "a"},
        },
        {
            "code": BusinessError.MISSING_UNIT_DIMS.value,
            "message": generic_msg,
            "context": {"pack_code": "3002", "tender_product_id": "b"},
        },
    ]

    primary = filter_primary_business_warnings(warnings)
    html = format_reason_for_failure_html(warnings)

    assert len(primary) == 1
    assert primary[0]["context"] == {"pack_code": "3002"}
    assert dims_msg in html or generic_msg in html
    assert html.count("unit dimensions are missing") == 1


@patch("app.workflows.nodes.gelita.record_tender_business_warnings.ActivityLogService")
def test_record_tender_business_warnings_single_row_for_duplicate_catalog_gaps(
    mock_activity_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_activity_cls.return_value = mock_svc
    msg = "Unit dimensions are missing."
    state = _tender_created_state()
    state.data["tender_business_warnings"] = [
        {
            "code": BusinessError.MISSING_UNIT_DIMS.value,
            "message": msg,
            "context": {"pack_code": "3002", "tender_product_id": "a"},
        },
        {
            "code": BusinessError.MISSING_UNIT_DIMS.value,
            "message": msg,
            "context": {"pack_code": "3002", "tender_product_id": "b"},
        },
    ]

    record_tender_business_warnings(state)

    mock_svc.record_exception.assert_called_once()
    write = mock_svc.record_exception.call_args[0][0]
    assert write.description == msg
    assert write.metadata is None


def test_filter_primary_business_warnings_suppresses_pack_profile_dependents() -> None:
    pack_msg = format_error_message(BusinessError.MISSING_PACK_CODE, pack_code="5326")
    qty_msg = format_error_message(BusinessError.MISSING_QTY_PER_UNIT, pack_code="5326")
    total_msg = format_error_message(BusinessError.MISSING_TOTAL_QTY, pack_code="5326")
    dims_msg = format_error_message(BusinessError.MISSING_UNIT_DIMS, pack_code="5326")
    warnings = [
        {"code": BusinessError.MISSING_PACK_CODE.value, "message": pack_msg},
        {"code": BusinessError.MISSING_QTY_PER_UNIT.value, "message": qty_msg},
        {"code": BusinessError.MISSING_TOTAL_QTY.value, "message": total_msg},
        {"code": BusinessError.MISSING_UNIT_DIMS.value, "message": dims_msg},
    ]

    primary = filter_primary_business_warnings(warnings)
    html = format_reason_for_failure_html(warnings)

    assert primary == [{"code": BusinessError.MISSING_PACK_CODE.value, "message": pack_msg}]
    assert pack_msg in html
    assert qty_msg not in html
    assert total_msg not in html
    assert dims_msg not in html
    assert "Please update the field highlighted in red manually." in html


def test_filter_primary_business_warnings_suppresses_customer_name_when_address_missing() -> None:
    del_code = "44120611"
    address_msg = format_error_message(
        BusinessError.MISSING_DELIVERY_ADDRESS, del_code=del_code
    )
    customer_msg = format_error_message(
        BusinessError.MISSING_CUSTOMER_NAME, del_code=del_code
    )
    warnings = [
        {
            "code": BusinessError.MISSING_DELIVERY_ADDRESS.value,
            "message": address_msg,
            "context": {"del_code": del_code},
        },
        {
            "code": BusinessError.MISSING_CUSTOMER_NAME.value,
            "message": customer_msg,
            "context": {"del_code": del_code},
        },
    ]

    primary = filter_primary_business_warnings(warnings)
    html = format_reason_for_failure_html(warnings)

    assert primary == [
        {
            "code": BusinessError.MISSING_DELIVERY_ADDRESS.value,
            "message": address_msg,
            "context": {"del_code": del_code},
        }
    ]
    assert address_msg in html
    assert customer_msg not in html


def test_filter_primary_business_warnings_keeps_customer_name_when_address_resolved() -> None:
    del_code = "41000100"
    customer_msg = format_error_message(
        BusinessError.MISSING_CUSTOMER_NAME, del_code=del_code
    )
    warnings = [
        {
            "code": BusinessError.MISSING_CUSTOMER_NAME.value,
            "message": customer_msg,
            "context": {"del_code": del_code},
        },
    ]

    primary = filter_primary_business_warnings(warnings)
    html = format_reason_for_failure_html(warnings)

    assert primary == warnings
    assert customer_msg in html


def test_record_business_gap_skips_dependent_when_ancestor_recorded() -> None:
    del_code = "44120611"
    data = {"event_type": "tender_created"}

    assert (
        record_business_gap(
            data,
            BusinessError.MISSING_DELIVERY_ADDRESS,
            del_code=del_code,
        )
        is True
    )
    assert (
        record_business_gap(
            data,
            BusinessError.MISSING_CUSTOMER_NAME,
            del_code=del_code,
        )
        is True
    )

    warnings = get_tender_business_warnings(data)
    assert len(warnings) == 1
    assert warnings[0]["code"] == BusinessError.MISSING_DELIVERY_ADDRESS.value
    assert warnings[0]["context"] == {"del_code": del_code}


@patch("app.workflows.nodes.gelita.record_tender_business_warnings.ActivityLogService")
def test_record_tender_business_warnings_writes_one_row_for_dependent_gaps(
    mock_activity_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_activity_cls.return_value = mock_svc
    del_code = "44120611"
    address_msg = format_error_message(
        BusinessError.MISSING_DELIVERY_ADDRESS, del_code=del_code
    )
    customer_msg = format_error_message(
        BusinessError.MISSING_CUSTOMER_NAME, del_code=del_code
    )
    state = _tender_created_state()
    state.data["tender_business_warnings"] = [
        {
            "code": BusinessError.MISSING_DELIVERY_ADDRESS.value,
            "message": address_msg,
            "context": {"del_code": del_code},
        },
        {
            "code": BusinessError.MISSING_CUSTOMER_NAME.value,
            "message": customer_msg,
            "context": {"del_code": del_code},
        },
    ]

    record_tender_business_warnings(state)

    mock_svc.record_exception.assert_called_once()
    write = mock_svc.record_exception.call_args[0][0]
    assert write.description == address_msg
    assert write.metadata is None


def test_record_business_gap_only_on_tender_created() -> None:
    data: dict = {}
    assert record_business_gap(data, BusinessError.MISSING_DELIVERY_DATE) is False
    assert get_tender_business_warnings(data) == []

    data["event_type"] = "tender_created"
    assert record_business_gap(data, BusinessError.MISSING_DELIVERY_DATE) is True
    warnings = get_tender_business_warnings(data)
    assert len(warnings) == 1
    assert warnings[0]["code"] == BusinessError.MISSING_DELIVERY_DATE.value


def test_record_business_gap_dedupes_same_warning() -> None:
    data = {"event_type": "tender_created"}

    assert record_business_gap(data, BusinessError.MISSING_DELIVERY_DATE) is True
    assert record_business_gap(data, BusinessError.MISSING_DELIVERY_DATE) is True

    warnings = get_tender_business_warnings(data)
    assert len(warnings) == 1
    assert warnings[0]["code"] == BusinessError.MISSING_DELIVERY_DATE.value


@patch("app.workflows.nodes.send_tender_email.send_email")
def test_send_tender_email_soft_fail_missing_delivery_date(mock_send_email) -> None:
    mock_send_email.return_value = {"success": True, "communication_id": "comm-1"}
    state = _tender_created_state(tender={"delivery_date": ""})

    result = send_tender_email(state)

    assert result is state
    assert "error" not in result.data
    mock_send_email.assert_called_once()
    body = mock_send_email.call_args.kwargs["body"]
    assert format_error_message(BusinessError.MISSING_DELIVERY_DATE) in body
    warnings = get_tender_business_warnings(result.data)
    assert warnings[0]["code"] == BusinessError.MISSING_DELIVERY_DATE.value


@patch("app.workflows.nodes.gelita.record_tender_business_warnings.ActivityLogService")
def test_record_tender_business_warnings_writes_exception_rows(
    mock_activity_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_activity_cls.return_value = mock_svc
    msg = format_error_message(BusinessError.MISSING_DELIVERY_DATE)
    state = _tender_created_state()
    state.data["tender_business_warnings"] = [
        {"code": BusinessError.MISSING_DELIVERY_DATE.value, "message": msg},
    ]

    record_tender_business_warnings(state)

    mock_svc.record_exception.assert_called_once()
    write = mock_svc.record_exception.call_args[0][0]
    assert write.description == msg
    assert write.metadata is None


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_business_error_clears_pause_type(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.domain.lifecycle_transition import LifecycleTransitionSequenceResult
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_svc.apply_sequence.return_value = LifecycleTransitionSequenceResult(
        activity_log_ids=["log-1"],
        lifecycle_updated=True,
    )
    mock_transition_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "workflow_lifecycle_id": "lifecycle-1",
            "error": {
                "code": BusinessError.MISSING_DELIVERY_DATE.value,
                "message": "missing date",
                "category": BusinessError.CATEGORY.value,
            },
        },
    )

    record_workflow_failure_node(state)

    commands = mock_svc.apply_sequence.call_args[0]
    assert commands[0].pause_type is None
